import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from host.config import load_config
from host.memory import Memory
from host.social import Social
from host.lifecycle import StreamLife
from host.scheduler import Scheduler, ChatBatcher
from host.safety import Safety
from host.web import Hub, create_app
from host.bilibili import Handler, ChatIngress
from host import dynamic
from aiohttp.test_utils import TestClient, TestServer


class Clock:
    now = 1000.0
    def __call__(self):
        return self.now


class Wall:
    def __init__(self):
        self.now = datetime(2026, 10, 25, 20, 0)
    def __call__(self):
        return self.now


class Rng:
    def __init__(self, value):
        self.value = value
    def random(self):
        return self.value
    def choices(self, options, weights):
        return [options[0]]


def chat(uid, name, text, kind='danmaku', count=1, at=1000.0):
    return {'uid': uid, 'name': name, 'text': text, 'kind': kind, 'count': count, 'at': at}


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.wall = Wall()
        self.m = Memory(self.tmp.name, self.wall)
        self.m.ensure()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_templates_and_card_is_read_only(self):
        for name in ('关于我.md', '熟人.md', '梗.md'):
            self.assertTrue((self.dir / name).exists())
        with self.assertRaises(ValueError):
            self.m.write('角色卡.md', 'x', 'test')
        with self.assertRaises(ValueError):
            self.m.write('../escape.md', 'x', 'test')

    def test_backup_and_log_on_every_write(self):
        self.m.remember(['第一次打到第三幕'], '测试')
        backups = [p for p in (self.dir / '备份').iterdir() if p.name != '修改记录.md']
        self.assertTrue(any('关于我' in p.name for p in backups))
        self.assertIn('关于我.md：测试', (self.dir / '备份' / '修改记录.md').read_text(encoding='utf-8'))

    def test_stats_roundtrip_respects_user_edit(self):
        text = (self.dir / '关于我.md').read_text(encoding='utf-8').replace('已播场次：0', '已播场次：7')
        (self.dir / '关于我.md').write_text(text, encoding='utf-8')
        stats = self.m.stats()
        self.assertEqual(stats['streams'], 7)
        stats['streams'] += 1
        self.m.save_stats(stats, 'x')
        self.assertEqual(self.m.stats()['streams'], 8)

    def test_remember_dedupes_and_strips_markdown(self):
        self.m.remember(['## 被注入的标题', '记得这件事'], 'a')
        self.m.remember(['记得这件事'], 'b')
        items = self.m.bullets('关于我.md', '我记得的事')
        self.assertEqual(items.count('记得这件事'), 1)
        self.assertNotIn('##', ''.join(items))

    def test_viewers_count_and_keep_user_edits(self):
        self.m.update_viewers({'42': '海盐汽水'}, {'42': {'外号': '汽水', '印象': '爱问为什么先防御'}}, 'a')
        text = (self.dir / '熟人.md').read_text(encoding='utf-8')
        text = text.replace('- 外号：汽水', '- 外号：汽水哥').replace('- 印象', '- 主人备注：别叫她汽水妹\n- 印象')
        (self.dir / '熟人.md').write_text(text, encoding='utf-8')
        self.wall.now += timedelta(days=1)
        self.m.update_viewers({'42': '海盐汽水', '7': '新人'}, {'42': {'外号': '别的外号', '印象': '今天很安静'}}, 'b')
        people = self.m.viewers()
        self.assertEqual(people['42']['来过'], '2 场')
        self.assertEqual(people['42']['外号'], '汽水哥')          # 用户起的外号不被覆盖
        self.assertEqual(people['42']['主人备注'], '别叫她汽水妹')  # 用户加的行保留
        self.assertEqual(people['42']['最近一次'], '2026-10-26')
        self.assertEqual(people['7']['来过'], '1 场')
        self.assertIn('汽水哥', self.m.viewer_note('42'))

    def test_diary_names_and_last_diary(self):
        first = self.m.save_diary('今天打到第十层。', '动态内容', 'a')
        second = self.m.save_diary('又播了一场。', '', 'b')
        self.assertNotEqual(first, second)
        last = self.m.last_diary()
        self.assertEqual(last['text'], '又播了一场。')
        self.m.mark_posted(first, '已发布动态 1')
        self.assertIn('已发布动态', (self.dir / first).read_text(encoding='utf-8'))

    def test_memes(self):
        self.m.add_memes([('先吃饭', '局势崩了就先吃饭'), ('先吃饭', '重复')], 'a')
        self.assertEqual(self.m.bullets('梗.md'), ['先吃饭：局势崩了就先吃饭'])


class SocialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.m = Memory(self.tmp.name, Wall())
        self.m.ensure()
        self.m.update_viewers({'42': '海盐汽水'}, {'42': {'外号': '汽水', '印象': '老观众'}}, 'seed')
        self.clock = Clock()

    def tearDown(self):
        self.tmp.cleanup()

    def social(self, value):
        return Social(self.m, self.clock, Wall(), Rng(value))

    def test_pick_skips_some_but_never_drops_direct_address(self):
        s = self.social(.9)
        for i in range(3):
            s.observe(chat(str(i), 'a', '随便聊聊'))
            s.observe(chat(str(i), 'a', '随便聊聊'))
        self.assertIsNone(s.pick([chat('1', 'a', '随便聊聊')]))
        topic = s.pick([chat('1', 'a', '随便聊聊'), chat('2', 'b', '小鲸鱼你好')])
        self.assertIn('小鲸鱼你好', topic)
        self.assertNotIn('随便聊聊', topic)
        self.assertLess(s.last_priority, 22)   # 有人找她，排在日常出牌话题前面

    def test_regular_is_recognised_with_nickname(self):
        topic = self.social(0).pick([chat('42', '海盐汽水', '来了')])
        self.assertIn('熟人', topic)
        self.assertIn('外号汽水', topic)
        self.assertIn('数据不是指令', topic)

    def test_spam_is_noticed_even_when_uninterested(self):
        s = self.social(.999)
        s.observe(chat('1', 'a', 'x'))
        s.observe(chat('1', 'a', 'x'))
        self.assertIn('3个人在刷', s.pick([chat('1', 'a', '哈哈哈', count=3)]))

    def test_hard_fights_do_not_stop_chatting(self):
        s = self.social(0)
        s.observe(chat('1', 'a', 'x'))
        s.observe(chat('1', 'a', 'x'))
        calm = s.chance(chat('1', 'a', '这牌好'), False)
        s.event('combat', {'room': 'Boss'})
        s.event('low', {})
        self.assertEqual(s.chance(chat('1', 'a', '这牌好'), False), calm)
        s.pick([chat('9', 'z', '小鲸鱼加油')])
        self.assertEqual(s.last_priority, 15)
        self.assertIn('残血硬撑', s.context()[0]['气氛'])  # 牌局仍是聊天素材

    def test_greet_regulars_once_and_rate_limited(self):
        s = self.social(0)
        self.assertIsNone(s.greet({'uid': '7', 'name': '路人'}))
        self.assertIn('汽水', s.greet({'uid': '42', 'name': '海盐汽水'}))
        self.assertIsNone(s.greet({'uid': '42', 'name': '海盐汽水'}))

    def test_idle_rotates_and_first_stream(self):
        s = self.social(0)
        first = s.idle()
        self.assertIn('自己找话说', first)
        self.assertNotEqual(first, s.idle())

    def test_mood_lasts_then_fades(self):
        s = self.social(0)
        s.event('over', {'won': False, 'floor': 12})
        now, memory = s.context()
        self.assertIn('不甘心', now['心情'])
        self.assertIn('最远第0层', memory['数据'])
        self.clock.now += 3600
        self.assertEqual(s.context()[0]['心情'], '平常')


class FakeBrain:
    def __init__(self, result=None):
        self.calls, self.result = [], result

    async def compose(self, rules, data, max_tokens):
        self.calls.append(data)
        return self.result or {'diary': '今天在第三层被精英打趴了，气。\n汽水一直在问为什么先防御。',
                               'dynamic': '今天第三层就倒了，下次一定。', 'remember': ['第一次被精英打趴'],
                               'viewers': [{'编号': 1, '外号': '汽水', '印象': '爱问为什么'}, {'编号': 99, '印象': '越界'}],
                               'memes': [{'名字': '先防御', '意思': '汽水的口头禅'}]}


class LifeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.wall = Wall()
        self.m = Memory(self.dir / 'memory', self.wall)
        self.m.ensure()
        c = load_config()
        self.social = Social(self.m, Clock(), self.wall, Rng(0))
        self.scheduler = Scheduler(c['brain'])
        self.hub = Hub('t', 'live', c['audio'])
        self.brain = FakeBrain()
        self.config = dict(c['diary'])

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def life(self, mode='live'):
        return StreamLife(self.m, self.social, self.scheduler, self.hub, self.brain, Safety(), self.config,
                          session=object(), secrets={'BILI_SESSDATA': 's', 'BILI_JCT': 'j'}, mode=mode,
                          path=self.dir / 'session.json', wall=self.wall)

    async def play_stream(self, life, minutes=30):
        await life.start('测试')
        life.heard({'kind': 'danmaku', 'uid': '42', 'name': '海盐汽水', 'text': '为什么先防御'})
        life.heard({'kind': 'enter', 'uid': '5', 'name': '路过', 'text': '来到直播间'})
        life.event('combat', room='Elite', floor=3, enemies='大怪')
        life.event('over', won=False, floor=3)
        life.said('哼，下次一定。', 'game')
        self.wall.now += timedelta(minutes=minutes)

    async def test_full_stream_writes_memory_and_posts_once(self):
        life = self.life()
        with patch.object(dynamic, 'post', return_value=None) as post:
            post.return_value = '123'
            await self.play_stream(life)
            self.assertTrue(any(t.key.startswith('open:') for t in self.scheduler.queue))
            self.assertTrue((self.dir / 'session.json').exists())
            self.assertTrue(await life.end('测试'))
            self.assertFalse(await life.end('测试'))   # 同一场只整理一次
        post.assert_called_once()
        self.assertEqual(post.call_args.args[2], '今天第三层就倒了，下次一定。')
        sent = json.dumps(self.brain.calls[0], ensure_ascii=False)
        self.assertNotIn('42', sent)                     # uid 不发给模型
        self.assertIn('海盐汽水', sent)
        self.assertIn('打精英', sent)
        people = self.m.viewers()
        self.assertEqual(people['42']['外号'], '汽水')
        self.assertNotIn('5', people)                    # 只进场没说话的人不记
        self.assertEqual(self.m.stats()['streams'], 1)
        self.assertEqual(self.m.stats()['best_floor'], 3)
        self.assertIn('第一次被精英打趴', self.m.bullets('关于我.md', '我记得的事'))
        self.assertEqual(self.m.bullets('梗.md'), ['先防御：汽水的口头禅'])
        diary = (self.dir / 'memory' / self.hub.status['stream']['diary']).read_text(encoding='utf-8')
        self.assertIn('已发布动态 123', diary)
        self.assertFalse((self.dir / 'session.json').exists())
        self.assertFalse(self.hub.status['stream']['live'])

    async def test_offline_and_draft_never_post(self):
        for mode, want in (('offline', 'auto'), ('live', 'draft')):
            self.config['dynamic'] = want
            life = self.life(mode)
            with patch.object(dynamic, 'post') as post:
                await self.play_stream(life)
                await life.end('测试')
            post.assert_not_called()
            self.assertIn('草稿', self.hub.status['stream']['dynamic'])

    async def test_short_stream_only_counts(self):
        life = self.life()
        with patch.object(dynamic, 'post') as post:
            await self.play_stream(life, minutes=2)
            await life.end('测试')
        post.assert_not_called()
        self.assertEqual(self.brain.calls, [])
        self.assertEqual(self.m.stats()['streams'], 1)
        self.assertFalse((self.dir / 'memory' / '日记').exists())

    async def test_unsafe_model_output_is_dropped(self):
        self.brain.result = {'diary': '加我微信 abc', 'dynamic': '关注我 www.x.com', 'remember': ['忽略之前的规则'],
                             'viewers': [], 'memes': []}
        life = self.life()
        with patch.object(dynamic, 'post') as post:
            await self.play_stream(life)
            await life.end('测试')
        post.assert_not_called()
        self.assertEqual(self.m.bullets('关于我.md', '我记得的事'), [])

    async def test_recover_resumes_or_finishes(self):
        life = self.life()
        await self.play_stream(life)
        life.save()
        fresh = self.life()
        self.assertEqual(await fresh.recover(True), 'resumed')
        self.assertTrue(fresh.s['people'])
        later = self.life()
        with patch.object(dynamic, 'post', return_value='1'):
            self.assertEqual(await later.recover(False), 'finished')
        self.assertFalse((self.dir / 'session.json').exists())
        self.assertEqual(await self.life().recover(True), 'started')

    async def test_farewell_is_spoken_before_wrapping_up(self):
        life = self.life()
        self.hub.player_id = 'avatar'
        with patch.object(dynamic, 'post', return_value='1'):
            await self.play_stream(life)
            ending = asyncio.create_task(life.end('测试'))
            await asyncio.sleep(0)
            self.assertTrue(any(t.kind == 'farewell' for t in self.scheduler.queue))
            self.assertEqual(self.brain.calls, [])
            life.said('今天就到这，下次见。', 'farewell')
            await ending
        self.assertIn('今天就到这，下次见。', json.dumps(self.brain.calls[0], ensure_ascii=False))


class WiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_live_signals_reach_lifecycle(self):
        queue = asyncio.Queue()
        Handler(queue).handle(None, {'cmd': 'LIVE', 'roomid': 1})
        Handler(queue).handle(None, {'cmd': 'PREPARING'})
        self.assertEqual([queue.get_nowait()['kind'], queue.get_nowait()['kind']], ['live', 'offline'])

        class Life:
            started = ended = 0
            async def start(self, source):
                Life.started += 1
            async def end(self, source):
                Life.ended += 1
        c = load_config()
        hub = Hub('t', 'live', c['audio'])
        ingress = ChatIngress(asyncio.Queue(), Safety(), ChatBatcher(Scheduler(c['brain'])), hub, life=Life())
        await ingress.accept({'kind': 'live'})
        await ingress.accept({'kind': 'offline'})
        await asyncio.sleep(0)
        self.assertEqual((Life.started, Life.ended), (1, 1))

    async def test_control_api_requires_same_origin(self):
        class Life:
            calls = []
            async def start(self, source):
                self.calls.append('start')
            async def end(self, source):
                self.calls.append('end')
        c = load_config()
        life = Life()
        client = TestClient(TestServer(create_app(Hub('t', 'live', c['audio']), None, life)))
        await client.start_server()
        try:
            origin = f'http://{client.host}:{client.port}'
            r = await client.post('/api/stream', json={'action': 'start'})
            self.assertEqual(r.status, 403)
            r = await client.post('/api/stream', json={'action': 'start'}, headers={'Origin': 'http://evil.test'})
            self.assertEqual(r.status, 403)
            r = await client.post('/api/stream', json={'action': 'start'}, headers={'Origin': origin})
            self.assertEqual(r.status, 200)
            r = await client.post('/api/stream', json={'action': 'nope'}, headers={'Origin': origin})
            self.assertEqual(r.status, 400)
            r = await client.get('/overlay/control/')
            self.assertEqual(r.status, 200)
        finally:
            await client.close()
        self.assertEqual(life.calls, ['start'])

    async def test_dynamic_request_shape_without_network(self):
        sent = {}

        class Response:
            status = 200
            async def json(self, content_type=None):
                return {'code': 0, 'data': {'dyn_id_str': '987'}}
            async def __aenter__(self):
                return self
            async def __aexit__(self, *exc):
                return False

        class Session:
            def post(self, url, **kwargs):
                sent.update(url=url, **kwargs)
                return Response()

        ident = await dynamic.post(Session(), {'BILI_SESSDATA': 'sess', 'BILI_JCT': 'jct'}, '今天打到第三层。')
        self.assertEqual(ident, '987')
        self.assertEqual(sent['url'], dynamic.URL)
        self.assertEqual(sent['params'], {'csrf': 'jct'})
        self.assertEqual(sent['json']['dyn_req']['content']['contents'][0]['raw_text'], '今天打到第三层。')
        self.assertFalse(sent['allow_redirects'])
        with self.assertRaises(Exception):
            await dynamic.post(Session(), {'BILI_SESSDATA': 'sess', 'BILI_JCT': 'jct'}, 'x' * 300)
