"""Zero-cost real-browser recovery test with a local Hub and WAV test tone.
Waits an actual 30 seconds for first timeout auto-recovery; seeds count=2 to test
third-time manual recovery without another minute of waiting. No provider/Bili/game calls.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
import shutil
from aiohttp import web
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from host.config import load_config
from host.web import Hub, create_app
from host.providers import AudioStore, TTS


async def main():
    config = load_config()
    c = {**config['audio'], 'playback_grace_seconds': .3}
    hub = Hub('协议测试 · 不产生真实收费', 'offline', c)
    store = AudioStore(ROOT / 'runtime' / 'audio', c)
    audio = await TTS(None, {}, store, offline=True).synthesize('离线测试')
    runner = web.AppRunner(create_app(hub, store), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', 8768).start()
    events, errors = [], []
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(str(ROOT / 'runtime' / 'edge-protocol-profile'),
                  executable_path=r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                  headless=True, viewport={'width': 1920, 'height': 1080}, args=['--autoplay-policy=no-user-gesture-required', '--disable-background-media-suspend', '--disable-renderer-backgrounding', '--disable-background-timer-throttling', '--disable-backgrounding-occluded-windows'])
        try:
            page = await context.new_page()
            page.on('pageerror', lambda e: errors.append(str(e)))
            await page.goto('http://127.0.0.1:8768/overlay/avatar/?debug')
            await asyncio.wait_for(hub.player_ready.wait(), 15)
            owner = hub.peers[hub.player_id]
            # Deliberately advertise a shorter duration than actual WAV to test missing ACK.
            short = {**audio, 'id': 'timeout-first', 'duration_s': .01, 'text': '超时测试', 'emotion': 'neutral'}
            started = time.monotonic()
            assert await hub.play(short) == 'timeout'
            assert owner.ack_timeouts == 1 and not owner.ready
            await asyncio.wait_for(hub.player_ready.wait(), 36)
            elapsed = time.monotonic() - started
            assert elapsed >= 29.5
            events.append({'step': 'first_timeout_auto_recovery', 'elapsed_seconds': round(elapsed, 2), 'ok': True})
            # Ended must reset the consecutive-failure counter, with the actual audio duration.
            ended = {**audio, 'id': 'normal-ended', 'text': '正常结束测试', 'emotion': 'happy'}
            assert await hub.play(ended) == 'ended'
            assert owner.ack_timeouts == 0
            events.append({'step': 'ended_resets_counter', 'ok': True})
            # Seed the counter to cover the third-time branch without waiting another 60s.
            owner.ack_timeouts = 2
            assert await hub.play({**short, 'id': 'timeout-third'}) == 'timeout'
            assert owner.manual_required and not owner.ready
            await page.locator('#unlock').wait_for(state='visible')
            assert '恢复' in await page.locator('#unlock').inner_text()
            await page.locator('#unlock').click()
            await asyncio.wait_for(hub.player_ready.wait(), 5)
            assert owner.ready and not owner.manual_required and owner.ack_timeouts == 0
            events.append({'step': 'third_timeout_requires_manual_click', 'ok': True, 'counter_seeded': 2})
            assert not errors, errors
            result = {'ok': True, 'paid_api_calls': 0, 'events': events, 'page_errors': errors}
            (ROOT / 'runtime' / 'browser-protocol.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            await context.close()
            shutil.rmtree(ROOT / 'runtime' / 'edge-protocol-profile', ignore_errors=True)
            await runner.cleanup()
            store.protected.discard(audio['id'])


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    temp = ROOT / 'runtime' / 'browser-temp'
    temp.mkdir(exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(temp)
    asyncio.run(main())
