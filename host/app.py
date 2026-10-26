import argparse
import asyncio
import logging
import signal
import time
import uuid
import aiohttp
from aiohttp import web
from .config import ROOT, load_config, load_secrets, validate_secrets
from .safety import Safety
from .scheduler import Scheduler, ChatBatcher
from .providers import Brain, TTS, AudioStore, ProviderError
from .game import GameTopics, GameReader
from .guidance import Guidance
from .bilibili import ChatIngress, listen, room_live
from .web import Hub, create_app
from .memory import Memory
from .social import Social
from .lifecycle import StreamLife

log = logging.getLogger('host')


async def worker(hub, scheduler, batcher, brain, tts, max_speeches=0, social=None, life=None, game_view=None, filler=None):
    completed = 0
    last_activity = time.monotonic()
    while True:
        batcher.flush()
        if max_speeches and completed >= max_speeches:
            await asyncio.sleep(0.5)
            continue
        if not hub.player_id:
            await asyncio.sleep(0.5)
            continue
        if not scheduler.queue and time.monotonic() - last_activity > scheduler.c['idle_seconds']:
            scheduler.offer(social.idle() if social else '直播间暂时安静，轻松聊一句爬塔的心情或邀请大家聊游戏。不编造刚发生的战况。',
                            'idle', 90, 'idle', ttl=15)
        if filler and hub.status['game_online'] and scheduler.game_due(scheduler.c.get('game_lines_min_per_minute', 0)):
            text = filler()  # 每分钟至少说几句牌局：没有新事件也找个角度聊
            if text:
                scheduler.offer(text, 'game', 40, f'fill:{time.monotonic():.0f}', ttl=10, screen=hub.status['game'].get('screen'))
        topic = scheduler.pop_ready()
        if not topic:
            await asyncio.sleep(0.3)
            continue
        last_activity = picked = time.monotonic()
        speech, spoken = None, None
        # 牌局台词绑定产生时的画面：打完仗还在讲战斗就不对了。先说后打的那句游戏在等，画面不会变；通关/阵亡不受影响。
        moved = lambda: (topic.kind == 'game' and not topic.gate and topic.priority > 0 and topic.screen
                         and hub.status['game'].get('screen') not in (None, topic.screen))
        try:
            if moved():
                continue
            game = game_view() if game_view and hub.status['game_online'] else hub.status['game']
            line = await brain.generate(topic, game, social.context() if social else None)
            thought = time.monotonic()
            if topic.kind == 'game' and topic.priority > 7 and time.monotonic() - topic.created > 25:
                continue  # 想好的时候画面早过去了：不念，也不花TTS的钱
            if moved():
                log.info('Dropped a %s line: the game screen changed while she was thinking', topic.kind)
                continue
            if not hub.player_id:
                continue  # Don't spend TTS credit if the avatar disappeared while thinking.
            audio = await tts.synthesize(line['text'])
            voiced = time.monotonic()
            speech = {**line, **audio}
            reason = await hub.play(speech)
            spoken = line['text'] if reason == 'ended' else None
            completed += 1
            # 延迟分解（只记数字）：排队、想台词、合成语音、念完。
            log.info('Speech completed id=%s kind=%s outcome=%s queued=%.1fs llm=%.1fs tts=%.1fs duration=%.2fs',
                     speech['id'], topic.kind, reason, picked - topic.created, thought - picked, voiced - thought, speech['duration_s'])
        except (ProviderError, aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            # Do not log exception bodies, URLs, prompts or generated text.
            detail = str(exc) if isinstance(exc, ProviderError) else type(exc).__name__
            log.warning('Speech pipeline failed (%s); retry only on next budgeted topic', detail)
        finally:
            if topic.gate:
                topic.gate.done.set()  # 说完、跳过或失败都放行，游戏不会因为她卡住
            if speech:
                tts.store.protected.discard(speech['id'])
            if life:
                life.said(spoken, topic.kind)
            last_activity = time.monotonic()


async def demo(queue, topics, hub, live_game=False, chat=True):
    await hub.player_ready.wait()
    examples = [('海盐汽水', '大肥鱼，为什么这次先叠格挡呀？'), ('深海潜水员', '这张牌看起来好厉害！'),
                ('鲸落', '加油，慢慢来就好'), ('珍珠泡泡', '送出 小花花 × 1')]
    cycle = 0
    while True:
        if not live_game:
            state = {'run_id': 'DEMO-NOT-A-REAL-RUN', 'screen': 'COMBAT', 'turn': 1,
                     'run': {'floor': cycle + 6, 'current_hp': 28, 'max_hp': 80, 'character_name': '铁甲战士'},
                     'combat': {'room_type': 'Elite', 'enemies': [{'name': '模拟精英'}], 'player': {'current_hp': 28, 'max_hp': 80}}}
            if not chat:  # 手动聊天测试用平静的地图画面
                state = {'run_id': 'DEMO-NOT-A-REAL-RUN', 'screen': 'MAP',
                         'run': {'floor': 6, 'current_hp': 52, 'max_hp': 80, 'character_name': '铁甲战士'}}
            topics.update(state)
            from .game import project_state
            await hub.status_update(game_online=False, game=project_state(state))
        for index, (name, text) in enumerate(examples if chat else []):
            await queue.put({'id': uuid.uuid4().hex, 'kind': 'gift' if index == 3 else 'danmaku', 'uid': str(index),
                             'name': name, 'text': text, 'medal': {'name': '深海', 'level': 6}, 'time': time.time()})
            await asyncio.sleep(6)
        if not chat:
            await asyncio.sleep(3600)  # 手动弹幕测试：局面固定，不刷出牌事件，免得盖过弹幕
            continue
        if not live_game:
            topics.event('decision_made', {'data': {'id': cycle + 1, 'action': 'play_card', 'reason': '先用防御挡住这回合的伤害，再等下一轮找关键攻击牌。'}})
        await asyncio.sleep(30)
        cycle += 1


async def run(args):
    config = load_config(args.config)
    if args.port:
        if not 1024 <= args.port <= 65535:
            raise ValueError('Invalid port')
        config['server']['port'] = args.port
    secrets = load_secrets()
    validate_secrets(secrets, args.offline)
    safety = Safety(secrets, config['safety']['extra_blocked_words'])
    mode = 'offline' if args.offline else 'dry-run' if args.dry_run else 'live'
    hub = Hub(config['server']['banner'], mode, config['audio'], config.get('overlay', {}))
    scheduler = Scheduler(config['brain'])
    memory = Memory()
    memory.ensure()
    social = Social(memory)
    batcher = ChatBatcher(scheduler, social)
    store = AudioStore(ROOT / 'runtime' / 'audio', config['audio'])
    ingress_queue = asyncio.Queue(maxsize=300)
    ingress = ChatIngress(ingress_queue, safety, batcher, hub, social)
    topics = GameTopics(scheduler, safety, config['game'])
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows: asyncio.run handles Ctrl+C; TaskGroup cancellation runs cleanup.
    proxy = bool(config.get('network', {}).get('use_system_proxy', True))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35), trust_env=proxy) as session:
        brain = Brain(session, secrets, config, safety, args.offline, memory=memory)
        tts = TTS(session, secrets, store, args.offline)
        life = StreamLife(memory, social, scheduler, hub, brain, safety, config['diary'], session, secrets, mode)
        if mode == 'live':
            brain.on_viewer_memory = life.remember_viewer
        ingress.life, topics.hook = life, life.event
        guidance = Guidance(config['brain'])
        def advise(name, text):
            if guidance.add(name, text):
                log.info('Viewer advice queued for the game (v%s)', guidance.version)
        brain.on_advice = advise
        topics.guidance = guidance
        async def narrate(payload):
            # 形象页没开就没人能说话：直接放行，别让游戏白等。
            return await topics.narrate(payload) if hub.player_id else False
        runner = web.AppRunner(create_app(hub, store, life, ingress_queue if args.manual_chat else None, narrate, guidance), access_log=None)
        await runner.setup()
        await web.TCPSite(runner, config['server']['host'], config['server']['port']).start()
        log.info('Host ready http://127.0.0.1:%s mode=%s (no game write operations)', config['server']['port'], mode)
        tasks = []
        try:
            async with asyncio.TaskGroup() as group:
                for coro in (worker(hub, scheduler, batcher, brain, tts, args.max_speeches, social, life, topics.brief, topics.filler), ingress.run(), store.sweep()):
                    tasks.append(group.create_task(coro))
                live_check = mode == 'live' and config['bilibili']['enabled']
                tasks.append(group.create_task(life.recover(await room_live(session, secrets) if live_check else None)))
                if (not args.dry_run or args.live_game) and config['game']['enabled']:
                    reader = GameReader(session, secrets.get('STS2_AGENT_URL') or 'http://127.0.0.1:8080', topics, hub, config['game'])
                    tasks.extend([group.create_task(reader.snapshots()), group.create_task(reader.stream())])
                if not args.dry_run and config['bilibili']['enabled']:
                    tasks.append(group.create_task(listen(secrets, config['bilibili'], ingress_queue, hub, proxy)))
                if args.dry_run:
                    tasks.append(group.create_task(demo(ingress_queue, topics, hub, args.live_game, not args.manual_chat)))
                await stop.wait()
                for task in tasks:
                    task.cancel()
        finally:
            await runner.cleanup()


def main():
    parser = argparse.ArgumentParser(description='大肥鱼 AI 直播主持；游戏 API 严格只读')
    parser.add_argument('--config', help='optional YAML overrides')
    parser.add_argument('--port', type=int)
    parser.add_argument('--dry-run', action='store_true', help='synthetic chat/game, real paid DeepSeek + ElevenLabs')
    parser.add_argument('--offline', action='store_true', help='implies dry-run; fixed text + test tone, zero paid APIs')
    parser.add_argument('--live-game', action='store_true', help='in dry-run read real STS2 instead of fake game')
    parser.add_argument('--manual-chat', action='store_true', help='implies dry-run; no fake danmaku, type your own on /overlay/control/')
    parser.add_argument('--max-speeches', type=int, default=0, help='stop generating after N speeches, 0 = unlimited')
    args = parser.parse_args()
    if args.offline or args.manual_chat:
        args.dry_run = True
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    for logger in ('aiohttp.access', 'aiohttp.client'):
        logging.getLogger(logger).setLevel(logging.CRITICAL)
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Keep keys out even if an upstream library attaches a URL/header to its exception.
        log.error('Host stopped (%s); check configuration and connectivity; no secret details logged', type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
