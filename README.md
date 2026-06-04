# UI Navigator Agent System

An AI-powered system that uses Claude with Playwright MCP to navigate web applications step by step.

## Overview

Claude controls a live browser through the [Playwright MCP server](https://www.npmjs.com/package/@playwright/mcp). Instead of generating a static plan upfront, the agent reads each page, chooses the next action, and adapts when the UI differs from expectations.

**Components:**
- **Browser Agent**: Claude agent loop with Playwright MCP tools
- **Orchestrator**: CLI entry point and run management

## Features

- Works with any web app and task
- Live page snapshots drive decisions (no blind selector guessing)
- Handles login when credentials are provided, or pauses for manual login in the visible browser

## Setup

### Prerequisites

- Python 3.10+
- Node.js 18+ (for `npx` and Playwright MCP)
- Google Chrome
- Anthropic API key

### Installation

1. Clone this repository

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Create a `.env` file:
```bash
ANTHROPIC_API_KEY=your_key_here
# Optional
# CLAUDE_MODEL=claude-sonnet-4-20250514
# AGENT_MAX_ITERATIONS=40
# HEADLESS=true
```

Get your Anthropic API key from: https://console.anthropic.com/settings/keys

On first run, `npx` downloads `@playwright/mcp` automatically.

## Quick Start

```bash
# Public website (URL inferred from task)
python main.py "How do I search on Google?"

# With login credentials
python main.py "How do I create a project in Linear?" "your@email.com" "password"

# With explicit URL
python main.py "How do I filter a database?" "https://www.notion.so"
```

**What happens:**
1. Playwright MCP launches Chrome
2. Claude navigates the site using browser tools (`browser_snapshot`, `browser_click`, etc.)
3. A `summary.md` is written to the run folder under `runs/`

## Usage

```bash
python main.py "task description" [url_or_email] [password_or_url] [password]
```

**Examples:**
```bash
python main.py "How do I search on Google?"
python main.py "How do I create a project in Linear?" "your@email.com" "password"
python main.py "How do I filter a database?" "https://www.notion.so"
```

## Output

Each run creates a folder under `runs/run_<timestamp>/` with MCP logs and `summary.md`.

## How It Works

1. **Task input**: Natural language task (and optional URL/credentials)
2. **MCP session**: Local Playwright MCP server exposes browser tools to Claude
3. **Agent loop**: Claude reads the page, acts, verifies, and repeats until done
4. **Output**: Written summary in the run folder

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | required | Anthropic API key |
| `CLAUDE_MODEL` | `claude-sonnet-4-20250514` | Claude model |
| `AGENT_MAX_ITERATIONS` | `40` | Max agent tool-use turns |
| `HEADLESS` | `false` | Set to `true` for headless Chrome |
| `MCP_COMMAND` | `npx` | Command to launch Playwright MCP |
| `MCP_ARGS` | `-y @playwright/mcp@latest --browser chrome` | Extra MCP server args |

## Troubleshooting

- **Claude API errors**: Check `ANTHROPIC_API_KEY` and quota
- **`npx` / Node errors**: Install Node.js 18+ and ensure `npx` is on your PATH
- **Chrome not found**: Install Google Chrome
- **Login issues**: Run without `HEADLESS=true` so you can log in manually when prompted
- **Agent stops early**: Increase `AGENT_MAX_ITERATIONS`

## License

MIT
