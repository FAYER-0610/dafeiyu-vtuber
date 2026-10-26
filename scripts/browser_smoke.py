"""Optional Windows Edge/Playwright browser E2E. Default offline; --real costs one
DeepSeek generation and one ElevenLabs synthesis. Uses only a project-local browser profile.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
import aiohttp
from playwright.async_api import async_playwright
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'runtime'


async def check(args, process):
    base = f'http://127.0.0.1:{args.port}'
    prefix = 'browser' if args.real else 'browser-offline'
    async with aiohttp.ClientSession() as http:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError('Host exited before browser test')
            try:
                async with http.get(base + '/health', timeout=aiohttp.ClientTimeout(total=1)) as r:
                    if r.status == 200:
                        break
            except (aiohttp.ClientError, asyncio.TimeoutError):
                pass
            await asyncio.sleep(.2)
        else:
            raise RuntimeError('Host readiness timed out')
    errors, received, sent = [], [], []
    speech_event, done_event = asyncio.Event(), asyncio.Event()
    def frame(payload, direction):
        try:
            data = json.loads(payload)
        except (ValueError, TypeError):
            return
        if direction == 'received':
            if data.get('type') == 'speech':
                received.append(data)
                speech_event.set()
            elif data.get('type') == 'idle' and data.get('reason') == 'ended':
                done_event.set()
        elif data.get('type') == 'speech_done':
            sent.append(data)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(str(RUNTIME / 'edge-test-profile'), executable_path=args.browser,
                    headless=True, viewport={'width': 1920, 'height': 1080}, args=['--autoplay-policy=no-user-gesture-required', '--disable-background-media-suspend', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
        try:
            pages = {}
            for name in ['status', 'danmaku', 'subtitle', 'avatar']:
                page = await context.new_page()
                page.on('pageerror', lambda e: errors.append(str(e)))
                page.on('response', lambda response: errors.append(f'HTTP {response.status} {response.url}') if response.status >= 400 else None)
                page.on('console', lambda msg: errors.append(msg.text) if msg.type == 'error' and 'favicon' not in msg.text else None)
                if name == 'avatar':
                    def on_ws(ws):
                        ws.on('framereceived', lambda payload: frame(payload, 'received'))
                        ws.on('framesent', lambda payload: frame(payload, 'sent'))
                    page.on('websocket', on_ws)
                await page.goto(base + '/overlay/' + name + '/' + ('?debug' if name == 'avatar' else ''))
                pages[name] = page
            await asyncio.wait_for(speech_event.wait(), 100)
            await pages['subtitle'].locator('#box').wait_for(state='visible')
            # Prove actual WebAudio samples, not only a nominal play() call.
            await pages['avatar'].wait_for_function("() => { const s=document.querySelector('#debug')?.textContent||''; const m=s.match(/音量: ([0-9.]+)/); return m && Number(m[1])>0.001 && /rs[234]/.test(s); }", timeout=12000)
            speech = received[0]
            speaking_debug = await pages['avatar'].locator('#debug').inner_text()
            assert '情绪: ' + speech['emotion'] in speaking_debug
            if speech['emotion'] != 'neutral':
                assert '（emotion）' in speaking_debug, speaking_debug
            await pages['avatar'].locator('#debug').evaluate("el => el.style.opacity='0'")
            await asyncio.gather(*(page.screenshot(path=str(RUNTIME / f'{prefix}-{name}.png'), omit_background=True) for name, page in pages.items()))
            await asyncio.wait_for(done_event.wait(), speech['timeout_s'] + 5)
            assert sent and sent[-1]['id'] == speech['id'] and sent[-1]['status'] == 'ended', sent
            assert not errors, errors
            layout = await pages['danmaku'].locator('.chat').bounding_box()
            assert abs(layout['x'] - 24) <= 1 and abs(layout['y'] - 282) <= 1, layout
            status_layout = await pages['status'].locator('.status').bounding_box()
            assert status_layout['y'] + status_layout['height'] <= layout['y'], status_layout
            await pages['avatar'].wait_for_function("() => document.querySelector('#debug')?.textContent.includes('（idle）')", timeout=20000)
            debug = await pages['avatar'].locator('#debug').inner_text()
            images = [Image.open(RUNTIME / f'{prefix}-{n}.png').convert('RGBA') for n in ['status', 'danmaku', 'subtitle', 'avatar']]
            composite = Image.new('RGBA', (1920, 1080), '#081420')
            for image in images:
                composite.alpha_composite(image)
            composite.convert('RGB').save(RUNTIME / f'{prefix}-composite.png')
            result = {'ok': True, 'browser': await context.browser.version() if callable(getattr(context.browser, 'version', None)) else context.browser.version,
                      'real_providers': args.real, 'speech_id': speech['id'], 'text': speech['text'], 'duration_s': speech['duration_s'],
                      'ack': sent[-1], 'page_errors': errors, 'danmaku_bounds': layout, 'speaking_debug': speaking_debug, 'idle_debug': debug,
                      'note': 'Headless browser decoded/played audio and sent ended. OBS capture and human hearing are not tested.'}
            (RUNTIME / f'{prefix}-result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            await context.close()
            shutil.rmtree(RUNTIME / 'edge-test-profile', ignore_errors=True)


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--real', action='store_true')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--browser', default=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe')
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    temp = RUNTIME / 'browser-temp'
    temp.mkdir(exist_ok=True)
    os.environ['TEMP'] = str(temp)
    os.environ['TMP'] = str(temp)
    command = [sys.executable, '-m', 'host.app', '--dry-run', '--max-speeches', '1', '--port', str(args.port)]
    if not args.real:
        command.append('--offline')
    with (RUNTIME / 'browser-host.log').open('w', encoding='utf-8') as log:
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
