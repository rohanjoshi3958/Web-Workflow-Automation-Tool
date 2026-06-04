from .browser_agent import BrowserAgent


class Orchestrator:
    def __init__(self, run_dir='./runs'):
        self.agent = BrowserAgent(run_dir)
        self.run_dir = run_dir

    async def initialize(self):
        return None

    async def cleanup(self):
        return None

    async def process_task(self, task, app_url=None, credentials=None):
        if credentials is None:
            credentials = {}

        print(f"\n{'=' * 60}")
        print(f'Processing task: {task}')
        print(f"{'=' * 60}\n")

        result = await self.agent.run_task(task, app_url, credentials)

        if result.get('success'):
            print('\nTask summary:')
            print(result.get('summary', ''))
            print(f"\nRun logs: {result.get('run_dir')}")
        else:
            print(f"\nTask failed: {result.get('error')}")
            if result.get('error_detail'):
                print('\nDetails:\n' + result['error_detail'])

        return result
