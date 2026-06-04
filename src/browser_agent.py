import os
from datetime import datetime
from pathlib import Path

from anthropic import AsyncAnthropic
from anthropic.lib.tools.mcp import async_mcp_tool
from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

load_dotenv()

DISABLED_MCP_TOOLS = frozenset({'browser_take_screenshot'})

SYSTEM_PROMPT = """You are a UI automation agent with Playwright browser tools.

Complete the user's task by interacting with the live page. Work step by step:

1. Navigate to the target application (use the provided URL when given, otherwise infer it).
2. Call browser_snapshot when you need to understand the current page state.
3. Interact using browser_click, browser_type, browser_fill_form, browser_press_key, and related tools.
4. Do not take screenshots. Do not use browser_take_screenshot.
5. Prefer visible button/link text from the snapshot. Try alternatives if the first label fails.
6. Handle modals and autocomplete: wait for dialogs, select suggestions, dismiss blocking dropdowns.

Login:
- Only log in when the task requires authentication.
- If credentials are provided, use them.
- If a login wall appears and no credentials were provided, tell the user to log in manually in the visible browser window, then continue once authenticated.

When the task is finished or you cannot proceed, reply with a concise summary of what you accomplished."""


class BrowserAgent:
    def __init__(self, run_dir='./runs'):
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable is required')

        self.client = AsyncAnthropic(api_key=api_key)
        self.model = os.getenv('CLAUDE_MODEL', 'claude-sonnet-4-20250514')
        self.run_dir = Path(run_dir)
        self.max_iterations = int(os.getenv('AGENT_MAX_ITERATIONS', '40'))
        self.headless = os.getenv('HEADLESS', '').lower() in {'1', 'true', 'yes'}
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

    def _build_user_prompt(self, task, app_url=None, credentials=None):
        credentials = credentials or {}
        parts = [f'Task: {task}']

        if app_url:
            parts.append(f'Application URL: {app_url}')
        else:
            parts.append('Infer the application URL from the task if needed.')

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
            if tool.name not in DISABLED_MCP_TOOLS
        ]

    async def run_task(self, task, app_url=None, credentials=None):
        run_folder = self._create_run_folder()
        user_prompt = self._build_user_prompt(task, app_url, credentials)

        print(f'Run logs: {run_folder}')
        print('Starting Playwright MCP browser agent...\n')

        final_text = ''
        turns = 0

        try:
            async with stdio_client(self._mcp_server_params(run_folder)) as (read, write):
                async with ClientSession(read, write) as mcp_client:
                    await mcp_client.initialize()
                    tools_result = await mcp_client.list_tools()

                    runner = self.client.beta.messages.tool_runner(
                        model=self.model,
                        max_tokens=8192,
                        temperature=0.2,
                        max_iterations=self.max_iterations,
                        system=SYSTEM_PROMPT,
                        messages=[{'role': 'user', 'content': user_prompt}],
                        tools=self._mcp_tools(mcp_client, tools_result),
                    )

                    async for message in runner:
                        turns += 1
                        print(f'Agent turn {turns} ({message.stop_reason})')
                        for block in message.content:
                            if block.type == 'text' and block.text.strip():
                                final_text = block.text.strip()
                                preview = final_text.replace('\n', ' ')[:160]
                                print(f'  {preview}')

            summary_path = run_folder / 'summary.md'
            summary_path.write_text(
                '\n'.join([
                    f'# Task\n\n{task}\n',
                    f'## Result\n\n{final_text or "Task completed."}\n',
                ]),
                encoding='utf-8',
            )

            return {
                'success': True,
                'summary': final_text or 'Task completed.',
                'turns': turns,
                'run_dir': str(run_folder),
            }
        except Exception as error:
            print(f'Browser agent error: {error}')
            return {
                'success': False,
                'error': str(error),
                'turns': turns,
                'run_dir': str(run_folder),
            }
