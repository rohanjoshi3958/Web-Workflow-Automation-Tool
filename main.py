#!/usr/bin/env python3
"""
UI Navigator Agent - Main Entry Point

Claude + Playwright MCP browser agent. Provide a task and optional URL/credentials.
"""

import sys
import asyncio
import os
from dotenv import load_dotenv
from src import Orchestrator

load_dotenv()


async def run_task(task, app_url=None, credentials=None):
    """Run a single task."""
    if credentials is None:
        credentials = {}
    
    orchestrator = Orchestrator('./runs')
    
    try:
        await orchestrator.initialize()
        
        result = await orchestrator.process_task(task, app_url, credentials)
        
        return result
    except Exception as error:
        print(f'Error: {error}')
        return {'success': False, 'error': str(error)}
    finally:
        await orchestrator.cleanup()


def print_usage():
    """Print usage information."""
    print("""
UI Navigator Agent

Usage:
  python main.py "task"                       # Run single task (URL auto-detected)
  python main.py "task" "url"                 # Run with specific URL
  python main.py "task" "email" "password"    # With credentials (URL auto-detected)
  python main.py "task" "url" "email" "pass" # With URL and credentials

Examples:
  python main.py "How do I search on Google?"
  python main.py "How do I create a project in Linear?"
  python main.py "How do I filter a database in Notion?" "email@example.com" "password"
  python main.py "How do I create a project?" "https://linear.app" "email@example.com" "password"
""")


async def main():
    """Main entry point."""
    args = sys.argv[1:]
    
    if len(args) == 0 or args[0] in ['--help', '-h', 'help']:
        print_usage()
        return
    
    else:
        # Command line mode: python main.py "task" [url] [email] [password]]
        task = args[0]
        # Check if second arg is a URL (starts with http) or email
        app_url = None
        email = None
        password = None
        
        if len(args) > 1:
            if args[1].startswith('http'):
                app_url = args[1]
                email = args[2] if len(args) > 2 else None
                password = args[3] if len(args) > 3 else None
            else:
                # Second arg might be email
                email = args[1]
                password = args[2] if len(args) > 2 else None
        
        credentials = {}
        if email:
            credentials['email'] = email
        if password:
            credentials['password'] = password
        
        print(f'\nRunning task: {task}')
        if app_url:
            print(f'URL: {app_url}')
        else:
            print('URL: Will be auto-detected from task')
        print()
        
        await run_task(task, app_url, credentials)
        print('\nDone!')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n\nInterrupted by user. Goodbye!')
    except Exception as error:
        print(f'\nFatal error: {error}')

