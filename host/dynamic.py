"""下播后发一条纯文字动态。这是整个程序里唯一的 B 站写操作；没有任何发弹幕的代码。

接口参考 Alterssss/dsh-bili-whale 的 tools/commands/dynamic.mjs（MIT）：Web 端 /x/dynamic/feed/create/dyn。
凭据只放在请求头里，不进 URL 以外的日志；失败只返回 code，不回显上游正文。
"""
import aiohttp
from .providers import ProviderError

URL = 'https://api.bilibili.com/x/dynamic/feed/create/dyn'
NAV = 'https://api.bilibili.com/x/web-interface/nav'
UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36'
MAX_CHARS = 233


def _headers(secrets):
    cookie = f'SESSDATA={secrets["BILI_SESSDATA"]}; bili_jct={secrets["BILI_JCT"]}'
    if secrets.get('BILI_BUVID3'):
        cookie += f'; buvid3={secrets["BILI_BUVID3"]}'
    return {'Cookie': cookie, 'User-Agent': UA, 'Origin': 'https://t.bilibili.com', 'Referer': 'https://t.bilibili.com/'}


def ready(secrets):
    return bool(secrets.get('BILI_SESSDATA') and secrets.get('BILI_JCT'))


async def whoami(session, secrets):
    """只读：确认登录有效，返回账号昵称（不返回任何凭据）。"""
    async with session.get(NAV, headers=_headers(secrets), timeout=aiohttp.ClientTimeout(total=15), allow_redirects=False) as r:
        data = await r.json(content_type=None)
    if r.status != 200 or data.get('code') != 0 or not (data.get('data') or {}).get('isLogin'):
        raise ProviderError(f'Bilibili login check code {data.get("code")}')
    return str(data['data'].get('uname', ''))


async def post(session, secrets, text):
    if not ready(secrets):
        raise ProviderError('Bilibili cookie missing')
    text = text.strip()
    if not 0 < len(text) <= MAX_CHARS:
        raise ProviderError('Dynamic text length out of range')
    body = {'dyn_req': {'content': {'contents': [{'raw_text': text, 'type': 1, 'biz_id': ''}]}, 'scene': 1,
                        'meta': {'app_meta': {'from': 'create.dynamic.web', 'mobi_app': 'web'}}}}
    async with session.post(URL, params={'csrf': secrets['BILI_JCT']}, json=body, headers=_headers(secrets),
                            timeout=aiohttp.ClientTimeout(total=20), allow_redirects=False) as r:
        try:
            data = await r.json(content_type=None)
        except ValueError:
            data = {}
    if r.status != 200 or data.get('code') != 0:
        raise ProviderError(f'Bilibili dynamic HTTP {r.status} code {data.get("code")}')
    return str((data.get('data') or {}).get('dyn_id_str') or (data.get('data') or {}).get('dyn_id') or '')
