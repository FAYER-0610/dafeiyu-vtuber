"""Read-only health/state/SSE evidence. Never starts or changes a game."""
import asyncio
import json
from pathlib import Path
import sys
import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from host.config import load_secrets, validate_secrets
from host.game import sse_frames


async def main():
    secrets = load_secrets()
    validate_secrets(secrets, offline=True)
    base = (secrets.get('STS2_AGENT_URL') or 'http://127.0.0.1:8080').rstrip('/')
    result = {'read_only': True, 'events': []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=6)) as session:
        for endpoint in ('health', 'state'):
            async with session.get(base + '/' + endpoint, allow_redirects=False) as response:
                response.raise_for_status()
                data = (await response.json())['data']
                fields = ('status', 'mod_version', 'game_version', 'play_running') if endpoint == 'health' else ('screen', 'run_id', 'in_combat', 'turn')
                result[endpoint] = {k: data.get(k) for k in fields}
        try:
            async with asyncio.timeout(18):
                async with session.get(base + '/events/stream', timeout=aiohttp.ClientTimeout(total=None, sock_read=18), allow_redirects=False) as response:
                    result['sse_http'] = response.status
                    result['sse_content_type'] = response.headers.get('Content-Type')
                    async for kind, envelope in sse_frames(response.content):
                        data = envelope.get('data') or {}
                        result['events'].append({'event_id': envelope.get('event_id'), 'type': kind,
                                                 'data': {k: data[k] for k in ('run_id', 'screen', 'in_combat', 'turn', 'action_window_open') if k in data}})
                        if len(result['events']) >= 12:
                            break
        except asyncio.TimeoutError:
            result['observation_seconds'] = 18
    result['note'] = '只读订阅；stream_ready/session_started 是初始化快照，不代表实战发生。未人为启动战斗。'
    output = ROOT / 'runtime' / 'game-probe.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(main())
