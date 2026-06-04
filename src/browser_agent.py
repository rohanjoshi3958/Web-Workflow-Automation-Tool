import asyncio
import os
import re
import traceback
from datetime import date, datetime
from pathlib import Path

from anthropic import AsyncAnthropic, BadRequestError, RateLimitError
from anthropic.lib.tools.mcp import async_mcp_tool
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

ALLOWED_MCP_TOOLS = frozenset({
    'browser_navigate',
    'browser_click',
    'browser_type',
    'browser_fill_form',
    'browser_press_key',
    'browser_select_option',
    'browser_snapshot',
    'browser_wait_for',
    'browser_handle_dialog',
    'browser_tabs',
    'browser_navigate_back',
})

SYSTEM_PROMPT = """You are a UI automation agent with Playwright browser tools.

Rules:
- Work step by step. Be concise in text replies; prefer acting over narrating.
- browser_snapshot: always pass filename (e.g. snap_01.md) and depth: 6. Snapshots are saved to disk only—you cannot read those files. Use the small tool response, not re-snapshotting to "check" the page.
- Autocomplete: click field → browser_type value → browser_wait_for if needed → browser_click the suggestion text OR ArrowDown then Enter. Do not loop snapshots.
- Dates: if required but not given by the user, pick dates ~2–4 weeks out (range +3–7 days for round trips), click them in the calendar, confirm (Done/Apply/Search), continue until real results/listings appear—not only a price calendar grid.
- Login only when required; use provided credentials or ask the user to log in manually in the visible browser.
- Do not use browser_take_screenshot.

When done, summarize what you accomplished and stop calling tools."""


def _root_error(error: BaseException) -> BaseException:
    if isinstance(error, BaseExceptionGroup) and error.exceptions:
        return _root_error(error.exceptions[0])
    cause = error.__cause__
    if cause and cause is not error:
        return _root_error(cause)
    return error


def _format_error(error: BaseException) -> str:
    root = _root_error(error)
    if isinstance(root, RateLimitError):
        return (
            'Anthropic rate limit (429): too many input tokens per minute. '
            'Wait about 60 seconds and run again.'
        )
    if isinstance(root, BadRequestError):
        return f'API request rejected: {root}'
    return f'{type(root).__name__}: {root}'


def _format_error_detail(error: BaseException) -> str | None:
    root = _root_error(error)
    if isinstance(root, RateLimitError):
        return None
    lines = [''.join(traceback.format_exception(type(root), root, root.__traceback__))]
    if error is not root:
        lines.append(''.join(traceback.format_exception(type(error), error, error.__traceback__)))
    return ''.join(lines)


class BrowserAgent:
    def __init__(self, run_dir='./runs'):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is required')

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        self.run_dir = Path(run_dir)
        self.max_iterations = int(os.getenv('AGENT_MAX_ITERATIONS', '40'))
        self.max_tokens = int(os.getenv('AGENT_MAX_TOKENS', '2048'))
        self.headless = os.getenv('HEADLESS', '').lower() in {'1', 'true', 'yes'}
        self.rate_limit_retries = int(os.getenv('RATE_LIMIT_RETRIES', '2'))
        self.mcp_command = os.getenv('MCP_COMMAND', 'npx')
        self.mcp_args_prefix = os.getenv(
            'MCP_ARGS',
            '-y @playwright/mcp@latest --browser chrome',
        ).split()

    def _create_run_folder(self):
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        run_folder = self.run_dir / f'run_{timestamp}'
        run_folder.mkdir(parents=True, exist_ok=True)
        return run_folder

    def _task_specifies_dates(self, task: str) -> bool:
        task_lower = task.lower()
        if re.search(
            r'\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b|\b\d{4}-\d{2}-\d{2}\b',
            task_lower,
        ):
            return True
        month_names = (
            'january', 'february', 'march', 'april', 'may', 'june',
            'july', 'august', 'september', 'october', 'november', 'december',
            'jan', 'feb', 'mar', 'apr', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec',
        )
        if any(month in task_lower for month in month_names):
            return True
        return any(
            phrase in task_lower
            for phrase in ('today', 'tomorrow', 'next week', 'next month', 'this weekend')
        )

    def _build_user_prompt(self, task, app_url=None, credentials=None):
        credentials = credentials or {}
        parts = [f'Task: {task}', f"Today: {date.today().isoformat()}"]

        if app_url:
            parts.append(f'URL: {app_url}')

        if not self._task_specifies_dates(task):
            parts.append(
                'If dates are required but not specified, pick random reasonable dates and finish the flow.'
            )

        if credentials.get('email'):
            parts.append(f'Login email: {credentials["email"]}')
        if credentials.get('password'):
            parts.append(f'Login password: {credentials["password"]}')

        return '\n'.join(parts)

    def _mcp_server_params(self, run_folder: Path) -> StdioServerParameters:
        args = [
            *self.mcp_args_prefix,
            '--output-dir',
            str(run_folder.resolve()),
            '--output-mode',
            'file',
        ]
        if self.headless:
            args.append('--headless')

        return StdioServerParameters(command=self.mcp_command, args=args)

    def _mcp_tools(self, mcp_client, tools_result):
        return [
            async_mcp_tool(tool, mcp_client)
            for tool in tools_result.tools
            if tool.name in ALLOWED_MCP_TOOLS
        ]

    def _write_summary(self, run_folder: Path, task: str, final_text: str, error: str | None = None):
        sections = [f'# Task\n\n{task}\n']
        if error:
            sections.append(f'## Error\n\n{error}\n')
        sections.append(f'## Result\n\n{final_text or "Task completed."}\n')
        (run_folder / 'summary.md').write_text('\n'.join(sections), encoding='utf-8')

    async def _run_agent_loop(self, runner):
        final_text = ''
        turns = 0
        async for message in runner:
            turns += 1
            print(f'Agent turn {turns} ({message.stop_reason})')
            for block in message.content:
                if block.type == 'text' and block.text.strip():
                    final_text = block.text.strip()
                    preview = final_text.replace('\n', ' ')[:160]
                    print(f'  {preview}')
        return final_text, turns

    async def run_task(self, task, app_url=None, credentials=None):
        run_folder = self._create_run_folder()
        user_prompt = self._build_user_prompt(task, app_url, credentials)

        print(f'Run logs: {run_folder}')
        print('Starting Playwright MCP browser agent...\n')

        final_text = ''
        turns = 0
        agent_error = None
        agent_error_detail = None

        try:
            async with stdio_client(self._mcp_server_params(run_folder)) as (read, write):
                async with ClientSession(read, write) as mcp_client:
                    await mcp_client.initialize()
                    tools_result = await mcp_client.list_tools()

                    runner = self.client.beta.messages.tool_runner(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        temperature=0.2,
                        max_iterations=self.max_iterations,
                        system=SYSTEM_PROMPT,
                        messages=[{'role': 'user', 'content': user_prompt}],
                        tools=self._mcp_tools(mcp_client, tools_result),
                    )

                    for attempt in range(self.rate_limit_retries + 1):
                        try:
                            final_text, turns = await self._run_agent_loop(runner)
                            break
                        except RateLimitError as error:
                            if attempt >= self.rate_limit_retries:
                                raise
                            wait_seconds = 65
                            print(
                                f'\nRate limit hit (attempt {attempt + 1}). '
                                f'Waiting {wait_seconds}s before retry...\n'
                            )
                            await asyncio.sleep(wait_seconds)
        except Exception as error:
            agent_error = _format_error(error)
            agent_error_detail = _format_error_detail(error)
            print(f'\nAgent loop failed:\n{agent_error}')
            if agent_error_detail:
                print(agent_error_detail)

        self._write_summary(run_folder, task, final_text, agent_error)

        if agent_error:
            result = {
                'success': False,
                'error': agent_error,
                'turns': turns,
                'run_dir': str(run_folder),
                'summary': final_text,
            }
            if agent_error_detail:
                result['error_detail'] = agent_error_detail
            return result

        return {
            'success': True,
            'summary': final_text or 'Task completed.',
            'turns': turns,
            'run_dir': str(run_folder),
        }
