"""用户自己运行的动态探针。默认只读：检查登录是否有效，显示最近一篇日记里的动态草稿。

加 --post 才会真的把这条草稿发成 B 站动态（一次请求，不重试），可以用来手动补发。
不打印 Cookie、请求头或上游原始响应。
"""
import argparse
import asyncio
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiohttp
from host.config import load_secrets
from host import dynamic
from host.memory import Memory, diary_order
from host.providers import ProviderError


def latest_draft(memory):
    folder = memory.dir / '日记'
    for path in sorted(folder.glob('*.md'), key=diary_order, reverse=True) if folder.is_dir() else []:
        found = re.search(r'^##\s*动态\s*$\n(.*?)(?=^\s*（|^##\s|\Z)', path.read_text(encoding='utf-8-sig'), flags=re.M | re.S)
        if found and found.group(1).strip():
            return path, found.group(1).strip()
    return None, None


async def main(post):
    secrets, memory = load_secrets(), Memory()
    if not dynamic.ready(secrets):
        print('没有登录：先运行 login_bilibili.bat 用直播账号扫码。')
        return 1
    path, text = latest_draft(memory)
    async with aiohttp.ClientSession(trust_env=False) as session:
        try:
            print('登录有效，账号：', await dynamic.whoami(session, secrets))
        except ProviderError as exc:
            print('登录检查失败：', exc)
            return 1
        if not text:
            print('还没有带动态草稿的日记。')
            return 0
        print(f'最近的草稿（{path.name}，{len(text)} 字）：\n{text}')
        if not post:
            print('\n只读检查完成，没有发布。确认要发就加 --post 再运行一次。')
            return 0
        try:
            ident = await dynamic.post(session, secrets, text)
        except ProviderError as exc:
            print('发布失败：', exc)
            return 1
    memory.mark_posted(f'日记/{path.name}', f'手动发布动态 {ident}')
    print('已发布：', f'https://t.bilibili.com/{ident}' if ident else '（接口没返回编号）')
    return 0


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description='检查登录 / 手动发布最近一篇日记的动态')
    parser.add_argument('--post', action='store_true', help='真的发布（一次，不重试）')
    raise SystemExit(asyncio.run(main(parser.parse_args().post)))
