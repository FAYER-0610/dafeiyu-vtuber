"""User-initiated QR login. No account action other than the explicitly requested login.
Use a small/secondary account. Never print cookies, polling keys or response bodies.
"""
import argparse
import asyncio
from pathlib import Path
import sys
import time
import re
import uuid
import aiohttp
import qrcode

ROOT = Path(__file__).resolve().parents[1]
GENERATE = 'https://passport.bilibili.com/x/passport-login/web/qrcode/generate'
POLL = 'https://passport.bilibili.com/x/passport-login/web/qrcode/poll'
SPI = 'https://api.bilibili.com/x/frontend/finger/spi'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36',
           'Referer': 'https://www.bilibili.com/'}


def save_cookies(values):
    target = ROOT / '.env'
    temporary = ROOT / f'.env.login.{uuid.uuid4().hex}.tmp'
    try:
        if set(values) != {'BILI_SESSDATA', 'BILI_JCT', 'BILI_BUVID3'}:
            raise ValueError('Unexpected credential field')
        if any(not value or '\n' in value or '\r' in value for value in values.values()):
            raise ValueError('Invalid credential value')
        existing = target.read_text(encoding='utf-8') if target.exists() else ''
        encoded = {key: "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'" for key, value in values.items()}
        lines, seen = [], set()
        for line in existing.splitlines():
            match = re.match(r'^\s*(?:export\s+)?([A-Za-z_]\w*)\s*=', line)
            key = match.group(1) if match else None
            if key in encoded:
                lines.append(f'{key}={encoded[key]}')
                seen.add(key)
            else:
                lines.append(line)
        lines.extend(f'{key}={encoded[key]}' for key in encoded if key not in seen)
        # Atomic replacement wholly inside the project; no system-temp copy of secrets.
        temporary.touch(mode=0o600, exist_ok=False)
        temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        temporary.chmod(0o600)
        temporary.replace(target)
        target.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


async def run(generate_only):
    async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=20), trust_env=False) as session:
        async with session.get(GENERATE, allow_redirects=False) as r:
            r.raise_for_status()
            result = await r.json()
        if result.get('code') != 0 or not result.get('data', {}).get('qrcode_key'):
            raise ValueError('二维码接口未返回有效数据')
        data = result['data']
        qr = qrcode.QRCode(border=2)
        qr.add_data(data['url'])
        qr.make(fit=True)
        output = ROOT / 'runtime' / 'bilibili-login.png'
        output.parent.mkdir(parents=True, exist_ok=True)
        qr.make_image(fill_color='black', back_color='white').save(output)
        print('请用直播账号的 B站 App 扫码；切勿将此二维码截图分享给他人。')
        qr.print_ascii(invert=True)
        print(f'二维码 PNG 已保存：{output}')
        if generate_only:
            # Read-only status probe, no user authorization and no .env mutation.
            async with session.get(POLL, params={'qrcode_key': data['qrcode_key']}, allow_redirects=False) as r:
                r.raise_for_status()
                status = (await r.json()).get('data', {}).get('code')
            print(f'生成测试完成，poll 状态码={status}；未登录、未写入 Cookie。二维码约3分钟有效。')
            return
        deadline, previous = time.monotonic() + 190, None
        while time.monotonic() < deadline:
            async with session.get(POLL, params={'qrcode_key': data['qrcode_key']}, allow_redirects=False) as r:
                r.raise_for_status()
                payload = await r.json()
                response_cookies = {k: v.value for k, v in r.cookies.items()}
            if payload.get('code') != 0:
                raise ValueError('登录轮询接口返回错误')
            code = payload['data']['code']
            if code != previous:
                print({86101: '等待扫码…', 86090: '已扫码，请在 App 里确认。', 86038: '二维码已过期，请重新运行。', 0: '扫码登录成功，正在保存本地凭据。'}.get(code, '等待登录状态更新…'))
                previous = code
            if code == 86038:
                return
            if code == 0:
                cookies = {c.key: c.value for c in session.cookie_jar}
                cookies.update(response_cookies)
                if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
                    raise ValueError('登录成功但接口未设置完整 Cookie；未改动 .env，请重试')
                buvid3 = cookies.get('buvid3', '')
                if not buvid3:
                    async with session.get(SPI, allow_redirects=False) as r:
                        r.raise_for_status()
                        fingerprint = await r.json()
                    buvid3 = fingerprint.get('data', {}).get('b_3', '')
                if not buvid3:
                    raise ValueError('未取得 buvid3；未改动 .env，请重试')
                save_cookies({'BILI_SESSDATA': cookies['SESSDATA'], 'BILI_JCT': cookies['bili_jct'], 'BILI_BUVID3': buvid3})
                output.unlink(missing_ok=True)
                print('已安全更新 .env 中 BILI_SESSDATA / BILI_JCT / BILI_BUVID3；其他配置不变。')
                print('请设置 .env 中 BILI_ROOM_ID 为目标直播间号，然后重启主播程序。')
                return
            await asyncio.sleep(2)
        print('二维码等待超时，请重新运行。')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='B站直播账号扫码登录，只把凭据写到本项目 .env')
    parser.add_argument('--generate-only', action='store_true', help='只生成二维码与检查 poll；不登录、不改 .env')
    args = parser.parse_args()
    try:
        asyncio.run(run(args.generate_only))
    except KeyboardInterrupt:
        print('已取消；已有凭据未改动。')
    except Exception as exc:
        print(f'扫码流程失败（{type(exc).__name__}）。请检查网络后重试；未打印凭据。')
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
