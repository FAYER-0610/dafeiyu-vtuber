"""Real app E2E. Default: ONE paid DeepSeek + ONE ElevenLabs request.
--offline: fixed text + WAV test tone, no paid services. No Bilibili login/connect.
"""
import argparse
import asyncio
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import aiohttp
from mutagen.mp3 import MP3

ROOT = Path(__file__).resolve().parents[1]


async def check(args, process):
    base = f'http://127.0.0.1:{args.port}'
    async with aiohttp.ClientSession() as session:
        for _ in range(80):
            if process.poll() is not None:
                raise RuntimeError('Host exited; inspect runtime/smoke-host.log')
            try:
                async with session.get(base + '/health', timeout=aiohttp.ClientTimeout(total=1)) as response:
                    if response.status == 200:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(.25)
        else:
            raise RuntimeError('Host not ready')
        for path in ['/overlay/danmaku/', '/overlay/subtitle/', '/overlay/status/', '/overlay/avatar-placeholder/',
                     '/overlay/avatar/', '/overlay/avatar/avatar.js', '/overlay/avatar/avatar.json', '/shared/socket.js']:
            async with session.get(base + path) as r:
                assert r.status == 200, (path, r.status)
                assert len(await r.read()) > 10
        seen, received = set(), None
        async with session.ws_connect(base + '/ws') as avatar, session.ws_connect(base + '/ws') as viewer:
            async with asyncio.timeout(115):
                while True:
                    d = await avatar.receive_json()
                    seen.add(d['type'])
                    if d['type'] == 'hello':
                        client_id = d['client_id']
                        await avatar.send_json({'type': 'hello', 'role': 'avatar', 'ready': True})
                    elif d['type'] == 'speech':
                        assert d['player_id'] == client_id
                        assert 0 < len(d['text']) <= 300
                        assert d['audio_url'].startswith('/audio/')
                        async with session.get(base + d['audio_url']) as response:
                            assert response.status == 200
                            audio = await response.read()
                        duration = d['duration_s'] if args.offline else MP3(io.BytesIO(audio)).info.length
                        assert abs(duration - d['duration_s']) < .1
                        # Other observer pages see the same speech but are not authorized to play/ACK.
                        viewer_speech = None
                        while viewer_speech is None:
                            event = await viewer.receive_json()
                            if event['type'] == 'speech':
                                viewer_speech = event
                        assert viewer_speech['id'] == d['id']
                        await asyncio.sleep(duration)
                        await avatar.send_json({'type': 'speech_done', 'id': d['id'], 'status': 'ended'})
                        received = {'id': d['id'], 'text': d['text'], 'emotion': d['emotion'],
                                    'audio_bytes': len(audio), 'duration_s': round(duration, 3), 'audio_url': d['audio_url']}
                    elif d['type'] == 'idle' and received and d['last_speech_id'] == received['id']:
                        assert d['reason'] == 'ended', d
                        break
        assert 'danmaku' in seen
        result = {'ok': True, 'platform': sys.platform, 'python': sys.version.split()[0],
                  'mode': 'offline' if args.offline else 'real-providers', 'events': sorted(seen),
                  'formal_avatar_assets_http': '200', 'speech': received,
                  'note': 'Python WebSocket client simulates playback ACK; not proof of OBS audible output'}
        output = ROOT / 'runtime' / ('smoke-offline.json' if args.offline else 'smoke-real.json')
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print('Evidence:', output)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    (ROOT / 'runtime').mkdir(exist_ok=True)
    command = [sys.executable, '-m', 'host.app', '--dry-run', '--max-speeches', '1', '--port', str(args.port)]
    if args.offline:
        command += ['--offline']
    with (ROOT / 'runtime' / 'smoke-host.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        try:
            asyncio.run(check(args, process))
        finally:
            process.terminate()
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    main()
