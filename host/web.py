import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
import uuid
import zlib
from urllib.parse import urlsplit
from aiohttp import web, WSMsgType
from .config import ROOT


@dataclass
class Peer:
    ws: object
    role: str = 'viewer'
    ready: bool = False
    ack_timeouts: int = 0
    retry_at: float = 0
    manual_required: bool = False


class Hub:
    def __init__(self, banner, mode, audio_config, layout=None):
        self.peers = {}
        self.player_id = None
        self.player_ready = asyncio.Event()
        self.pending = None
        self.ack = None
        self.history = []
        self.audio_config = audio_config
        self.status = {'banner': banner, 'mode': mode, 'game_online': False, 'game_stream': False,
                       'bilibili': 'disabled', 'avatar_ready': False, 'speaking': False, 'game': {}, 'layout': layout or {},
                       'stream': {'live': False, 'since': None, 'diary': None, 'dynamic': None}}

    @staticmethod
    def packet(kind, **data):
        return {'type': kind, 'v': 1, 'ts': time.time(), **data}

    async def send(self, peer, packet):
        try:
            await asyncio.wait_for(peer.ws.send_json(packet, dumps=lambda d: json.dumps(d, ensure_ascii=False)), 2)
            return True
        except (ConnectionError, RuntimeError, asyncio.TimeoutError):
            await peer.ws.close()
            return False

    async def broadcast(self, kind, **data):
        packet = self.packet(kind, **data)
        peers = list(self.peers.values())
        if peers:
            await asyncio.gather(*(self.send(p, packet) for p in peers))

    async def status_update(self, **updates):
        if any(self.status.get(k) != v for k, v in updates.items()):
            self.status.update(updates)
            await self.broadcast('status', **self.status)

    async def elect(self):
        old = self.player_id
        eligible = [i for i, p in self.peers.items() if p.role == 'avatar' and p.ready and not p.ws.closed]
        if old not in eligible:
            self.player_id = eligible[0] if eligible else None
        if self.player_id:
            self.player_ready.set()
        else:
            self.player_ready.clear()
        for ident, p in list(self.peers.items()):
            if p.role == 'avatar':
                await self.send(p, self.packet('player', active=ident == self.player_id, client_id=ident))
        await self.status_update(avatar_ready=bool(self.player_id))

    async def receive(self, ident, value):
        peer = self.peers.get(ident)
        if not peer or not isinstance(value, dict):
            return
        if value.get('type') == 'hello':
            peer.role = 'avatar' if value.get('role') == 'avatar' else 'viewer'
            wants_ready = value.get('ready') is True and peer.role == 'avatar'
            if wants_ready and value.get('recovery') == 'manual':
                peer.ack_timeouts, peer.retry_at, peer.manual_required = 0, 0, False
            peer.ready = wants_ready and not peer.manual_required and time.monotonic() >= peer.retry_at
            if wants_ready and not peer.ready:
                await self.send(peer, self.packet('ready_reset', reason='ack_timeout',
                                                 retry_after_s=None if peer.manual_required else max(1, round(peer.retry_at - time.monotonic())),
                                                 manual_required=peer.manual_required))
            await self.elect()
        elif value.get('type') == 'speech_done' and self.pending:
            if (ident == self.pending['player_id'] and value.get('id') == self.pending['id']
                    and value.get('status') in ('ended', 'error') and self.ack and not self.ack.done()):
                self.ack.set_result(value['status'])

    async def play(self, speech):
        # One caller (host worker) owns play; keep protocol defensive for future extensions.
        if self.pending:
            raise RuntimeError('Concurrent speech prohibited')
        if not self.player_id or self.player_id not in self.peers:
            return 'no_player'
        timeout = speech['duration_s'] + self.audio_config['playback_grace_seconds']
        self.pending = {**speech, 'player_id': self.player_id, 'timeout_s': timeout}
        self.ack = asyncio.get_running_loop().create_future()
        reason = 'error'
        try:
            await self.status_update(speaking=True)
            await self.broadcast('emotion', emotion=speech['emotion'], speech_id=speech['id'])
            await self.broadcast('speech', **self.pending)
            try:
                reason = await asyncio.wait_for(self.ack, timeout)
            except asyncio.TimeoutError:
                reason = 'timeout'
            owner = self.peers.get(self.pending['player_id'])
            if reason != 'ended':
                await self.broadcast('speech_cancel', id=speech['id'], reason=reason)
                if owner:
                    owner.ready = False
                    if reason == 'timeout':
                        owner.ack_timeouts += 1
                        owner.manual_required = owner.ack_timeouts >= 3
                        delay = None if owner.manual_required else 30 * owner.ack_timeouts
                        owner.retry_at = time.monotonic() + (delay or 0)
                        await self.send(owner, self.packet('ready_reset', reason='ack_timeout', retry_after_s=delay,
                                                          manual_required=owner.manual_required))
                await self.elect()
            elif owner:
                owner.ack_timeouts, owner.retry_at, owner.manual_required = 0, 0, False
            return reason
        finally:
            self.pending, self.ack = None, None
            await self.status_update(speaking=False)
            await self.broadcast('emotion', emotion='neutral', speech_id=speech['id'])
            await self.broadcast('idle', last_speech_id=speech['id'], reason=reason, emotion='neutral')

    async def websocket(self, request):
        ws = web.WebSocketResponse(heartbeat=20, max_msg_size=16384)
        await ws.prepare(request)
        ident = uuid.uuid4().hex
        peer = Peer(ws)
        self.peers[ident] = peer
        await self.send(peer, self.packet('hello', client_id=ident))
        await self.send(peer, self.packet('status', **self.status))
        await self.send(peer, self.packet('history', items=list(self.history)))
        try:
            async for message in ws:
                if message.type == WSMsgType.TEXT:
                    try:
                        await self.receive(ident, json.loads(message.data))
                    except (ValueError, TypeError, KeyError):
                        continue
        finally:
            self.peers.pop(ident, None)
            await self.elect()
            # Do not ACK on disconnect. Wait duration+grace before starting anything else.
        return ws


def create_app(hub, audio_store, life=None, test_chat=None, narrate=None, guidance=None):
    @web.middleware
    async def local_only(request, handler):
        try:
            hostname = urlsplit('http://' + request.host).hostname
        except ValueError:
            raise web.HTTPForbidden()
        if hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise web.HTTPForbidden(text='Local host only')
        origin = request.headers.get('Origin')
        if origin and origin != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden(text='Same origin only')
        response = await handler(request)
        if not isinstance(response, web.WebSocketResponse):
            response.headers.update({'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
                                     'Cache-Control': 'no-store'})
            response.headers['Content-Security-Policy'] = (
                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "img-src 'self' data: https://*.hdslb.com; media-src 'self' blob:; "
                "connect-src 'self'; object-src 'none'; frame-ancestors 'self'"
            )
        return response

    app = web.Application(middlewares=[local_only], client_max_size=16384)
    app.router.add_get('/ws', hub.websocket)

    async def health(request):
        return web.json_response({'ok': True, 'service': 'xiaojingyu-host', 'protocol': 1,
                                  'mode': hub.status['mode'], 'avatar_ready': bool(hub.player_id)})
    app.router.add_get('/health', health)

    async def favicon(request):
        return web.Response(status=204)
    app.router.add_get('/favicon.ico', favicon)

    async def audio(request):
        name = request.match_info['name']
        if not re.fullmatch(r'[a-f0-9]{32}\.(mp3|wav)', name):
            raise web.HTTPNotFound()
        path = audio_store.directory / name
        if not path.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(path, headers={'Content-Type': 'audio/mpeg' if name.endswith('.mp3') else 'audio/wav'})
    app.router.add_get('/audio/{name}', audio)

    async def overlay(request):
        page = request.match_info['page']
        if page not in ('stage', 'danmaku', 'subtitle', 'status', 'avatar', 'avatar-placeholder', 'preview', 'control'):
            raise web.HTTPNotFound()
        if not request.path.endswith('/') and 'resource' not in request.match_info:
            raise web.HTTPFound(request.path + '/')
        relative = request.match_info.get('resource') or 'index.html'
        directory = (ROOT / 'overlay' / page).resolve()
        path = (directory / relative).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise web.HTTPNotFound(text='Overlay not installed')
        headers = {'Content-Type': 'video/webm'} if path.suffix.lower() == '.webm' else None
        return web.FileResponse(path, headers=headers)
    app.router.add_get('/overlay/{page}', overlay)
    app.router.add_get('/overlay/{page}/', overlay)
    app.router.add_get('/overlay/{page}/{resource:.*}', overlay)
    app.router.add_static('/shared/', ROOT / 'overlay' / 'shared', show_index=False)

    jobs = set()

    async def stream(request):
        # 控制页的开播/下播按钮。只接受本机同源页面发来的请求。
        if life is None or request.headers.get('Origin') != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden()
        try:
            action = (await request.json()).get('action')
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest()
        if action == 'start':
            await life.start('控制页')
        elif action == 'end':
            job = asyncio.create_task(life.end('控制页'))  # 要等道别说完，后台跑
            jobs.add(job)
            job.add_done_callback(jobs.discard)
        else:
            raise web.HTTPBadRequest()
        return web.json_response({'ok': True})
    app.router.add_post('/api/stream', stream)

    async def narrate_move(request):
        # 游戏 Mod 出手前来问一声（先说后打）：值得说就等她说完再回，不值得立刻回。
        # 浏览器跨站请求带 Origin，已被中间件挡掉；这里只收本机程序的 JSON。
        if narrate is None or request.content_type != 'application/json':
            raise web.HTTPForbidden()
        try:
            body = await request.json()
        except ValueError:
            raise web.HTTPBadRequest()
        if not isinstance(body, dict) or not isinstance(body.get('action'), str):
            raise web.HTTPBadRequest()
        return web.json_response({'ok': True, 'said': await narrate(body)})
    app.router.add_post('/api/narrate', narrate_move)

    async def viewer_guidance(request):
        # 游戏 Mod 每次决策前来读一眼最近的观众建议；只读，浏览器跨站请求已被中间件挡掉。
        if guidance is None:
            raise web.HTTPNotFound()
        return web.json_response({'ok': True, **guidance.snapshot()})
    app.router.add_get('/api/guidance', viewer_guidance)

    async def fake_chat(request):
        # 只有 --manual-chat 测试模式才注册：控制页手动模拟弹幕/进场/礼物，走和真弹幕一样的过滤。
        if request.headers.get('Origin') != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden()
        try:
            body = await request.json()
            name, text, kind = str(body['name'])[:24].strip() or '测试观众', str(body.get('text', ''))[:200], body.get('kind')
        except (ValueError, KeyError, TypeError, AttributeError):
            raise web.HTTPBadRequest()
        if kind not in ('danmaku', 'enter', 'gift'):
            raise web.HTTPBadRequest()
        text = {'enter': '来到直播间', 'gift': f'送出 {text or "小花花"} × 1'}.get(kind, text)
        if not text:
            raise web.HTTPBadRequest()
        uid = str(zlib.crc32(name.encode('utf-8')) % 10**8 + 1)  # 同一个昵称就是同一个人，方便测熟人
        try:
            test_chat.put_nowait({'id': uuid.uuid4().hex, 'kind': kind, 'uid': uid, 'name': name, 'text': text,
                                  'medal': {}, 'time': time.time()})
        except asyncio.QueueFull:
            raise web.HTTPServiceUnavailable()
        return web.json_response({'ok': True})
    if test_chat is not None:
        app.router.add_post('/api/test-chat', fake_chat)
        hub.status['manual_chat'] = True

    async def shutdown(app):
        await asyncio.gather(*(p.ws.close(code=1001, message=b'Host shutting down') for p in list(hub.peers.values())))
    app.on_shutdown.append(shutdown)
    return app
