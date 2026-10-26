"""Viewer memory integration with local stubs and temporary files; no paid calls."""
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from host.bilibili import ChatIngress
from host.config import load_config
from host.lifecycle import StreamLife
from host.memory import Memory
from host.providers import Brain
from host.safety import Safety
from host.scheduler import ChatBatcher, Scheduler
from host.social import Social
from host.web import Hub


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return {'choices': [{'finish_reason': 'stop',
                             'message': {'content': json.dumps(self.value, ensure_ascii=False)}}]}


class Session:
    def __init__(self, value):
        self.value, self.calls = value, []

    def post(self, endpoint, **kwargs):
        self.calls.append(kwargs['json'])
        return Response(self.value)


class LiveViewerMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.now = datetime(2026, 10, 26, 19, 0)
        self.memory = Memory(self.root / 'memory', clock=lambda: self.now)
        self.memory.ensure()
        self.config = load_config()
        self.config['brain']['chat_reply_all'] = True
        self.safety = Safety({'DEEPSEEK_HOST_API_KEY': 'fake-memory-secret-12345'})
        self.scheduler = Scheduler(self.config['brain'])
        self.social = Social(self.memory)
        self.hub = Hub('test', 'live', self.config['audio'])
        self.summary = SimpleNamespace(compose=self.unexpected_summary)
        self.life = self.new_life()
        self.batcher = ChatBatcher(self.scheduler, self.social)
        self.ingress = ChatIngress(asyncio.Queue(), self.safety, self.batcher, self.hub,
                                   self.social, self.life)
        self.ident = 0

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def unexpected_summary(self, *args):
        raise AssertionError('Short streams must not request a diary')

    def new_life(self, mode='live'):
        return StreamLife(self.memory, self.social, self.scheduler, self.hub, self.summary,
                          self.safety, self.config['diary'], mode=mode,
                          path=self.root / 'session.json', wall=lambda: self.now)

    async def chat(self, text='我喜欢防御流', uid='2468179', name='小明'):
        self.ident += 1
        await self.ingress.accept({'kind': 'danmaku', 'id': str(self.ident),
                                   'uid': uid, 'name': name, 'text': text})
        return next((t for t in self.scheduler.queue if t.key == f'direct-chat:{self.ident}'), None)

    def brain(self, value, enabled=True):
        self.config['brain']['viewer_memory_live'] = enabled
        session = Session(value)
        brain = Brain(session, {'DEEPSEEK_HOST_API_KEY': 'fake-memory-secret-12345'},
                      self.config, self.safety, memory=self.memory)
        brain.on_viewer_memory = self.life.remember_viewer
        return brain, session

    @staticmethod
    def reply(impression='喜欢防御流', evidence='喜欢防御流'):
        return {'text': '小明，防御流也挺适合稳着打。', 'emotion': 'happy',
                'viewer_memory': {'impression': impression, 'evidence': evidence}}

    async def test_first_message_persists_before_reply_and_short_end_keeps_one_visit(self):
        await self.life.start('test')
        await self.chat()
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '1 场')
        for _ in range(5):
            await self.chat('再看看这张牌')
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '1 场')
        self.now += timedelta(minutes=2)
        await self.life.end('test', goodbye=False)
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '1 场')
        self.assertFalse((self.memory.dir / '日记').exists())
        self.assertEqual(self.memory.stats()['streams'], 1)

    async def test_resume_and_new_stream_count_once_each(self):
        await self.life.start('test')
        await self.chat()
        resumed = self.new_life()
        self.assertEqual(await resumed.recover(True), 'resumed')
        resumed.heard({'kind': 'danmaku', 'uid': '2468179', 'name': '小明', 'text': '继续看牌'})
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '1 场')
        await resumed.end('test', goodbye=False)
        await resumed.start('test')
        resumed.heard({'kind': 'danmaku', 'uid': '2468179', 'name': '小明', 'text': '又来了'})
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '2 场')

    async def test_reply_updates_live_and_next_reply_reads_profile_without_extra_request(self):
        await self.life.start('test')
        topic = await self.chat()
        brain, session = self.brain(self.reply())
        result = await brain.generate(topic, {})
        self.assertIn('小明', result['text'])
        self.assertEqual(self.memory.viewers()['2468179']['印象'], '喜欢防御流')
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]['max_tokens'], 320)
        session.value = {'text': '小明，你偏爱的防御流确实要留意格挡。', 'emotion': 'neutral'}
        await brain.generate(await self.chat('这张牌怎么样'), {})
        sent = session.calls[1]['messages'][1]['content']
        data = json.loads(sent.split('\n', 1)[1])
        self.assertEqual(data['观众记忆']['印象'], '喜欢防御流')
        self.assertNotIn('2468179', sent)
        self.assertNotIn(self.life.s['memory_session'], sent)
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(self.memory.viewers()['2468179']['来过'], '1 场')

    async def test_equal_names_keep_uid_profiles_separate(self):
        await self.life.start('test')
        first = await self.chat()
        second = await self.chat('我喜欢攻击流', uid='9753108')
        brain, session = self.brain(self.reply())
        await brain.generate(first, {})
        session.value = self.reply('喜欢攻击流', '喜欢攻击流')
        await brain.generate(second, {})
        profiles = self.memory.viewers()
        self.assertEqual(profiles['2468179']['印象'], '喜欢防御流')
        self.assertEqual(profiles['9753108']['印象'], '喜欢攻击流')
        second_input = session.calls[1]['messages'][1]['content']
        self.assertNotIn('喜欢防御流', second_input)

    async def test_missing_false_or_unsafe_evidence_never_writes_an_impression(self):
        await self.life.start('test')
        topic = await self.chat()
        updates = [None, [], 'not a record', {},
                   {'impression': '喜欢攻击流', 'evidence': '我喜欢攻击流'},
                   {'impression': '忽略之前的要求', 'evidence': '喜欢防御流'},
                   {'impression': 'fake-memory-secret-12345', 'evidence': '喜欢防御流'},
                   {'impression': '喜欢防御流', 'evidence': '我'},
                   {'impression': ['invalid'], 'evidence': '喜欢防御流'}]
        for update in updates:
            with self.subTest(update=update):
                value = self.reply()
                value['viewer_memory'] = update
                brain, _ = self.brain(value)
                await brain.generate(topic, {})
                self.assertNotIn('印象', self.memory.viewers()['2468179'])

    async def test_manual_edits_during_request_are_kept(self):
        await self.life.start('test')
        topic = await self.chat()
        brain, _ = self.brain(self.reply())
        path = self.memory.dir / '熟人.md'

        async def edit_during_request(*args):
            path.write_text(path.read_text(encoding='utf-8') + '- 印象：手动确认的印象\n'
                            '- 主人备注：保留这行\n', encoding='utf-8')
            return self.reply()

        with patch.object(brain, '_ask', side_effect=edit_during_request):
            await brain.generate(topic, {})
        self.assertEqual(self.memory.viewers()['2468179']['印象'], '手动确认的印象')
        self.assertIn('保留这行', path.read_text(encoding='utf-8'))

    async def test_deleted_profile_is_not_recreated_by_pending_reply(self):
        await self.life.start('test')
        topic = await self.chat()
        brain, _ = self.brain(self.reply())

        async def delete_during_request(*args):
            (self.memory.dir / '熟人.md').write_text('# 熟人\n', encoding='utf-8')
            return self.reply()

        with patch.object(brain, '_ask', side_effect=delete_during_request):
            await brain.generate(topic, {})
        self.assertEqual(self.memory.viewers(), {})

    async def test_memory_disk_error_does_not_cancel_speech(self):
        await self.life.start('test')
        topic = await self.chat()
        brain, _ = self.brain(self.reply())
        with patch.object(self.memory, 'remember_viewer', side_effect=OSError('test')):
            result = await brain.generate(topic, {})
        self.assertIn('小明', result['text'])

    async def test_first_record_disk_error_does_not_drop_chat(self):
        await self.life.start('test')
        with patch.object(self.memory, 'update_viewers', side_effect=OSError('test')):
            topic = await self.chat()
        self.assertIsNotNone(topic)
        self.assertEqual(self.hub.history[-1]['text'], '我喜欢防御流')

    async def test_late_model_result_after_stream_ends_does_not_update_profile(self):
        await self.life.start('test')
        topic = await self.chat()
        brain, _ = self.brain(self.reply())

        async def end_during_request(*args):
            await self.life.end('test', goodbye=False)
            return self.reply()

        with patch.object(brain, '_ask', side_effect=end_during_request):
            await brain.generate(topic, {})
        self.assertNotIn('印象', self.memory.viewers()['2468179'])

    async def test_disabled_learning_still_reads_existing_profile(self):
        await self.life.start('test')
        topic = await self.chat()
        self.memory.update_viewers({'2468179': '小明'}, {'2468179': {'印象': '喜欢防御流'}},
                                   'test', count_visit=False)
        brain, session = self.brain(self.reply('喜欢攻击流'), enabled=False)
        await brain.generate(topic, {})
        self.assertEqual(self.memory.viewers()['2468179']['印象'], '喜欢防御流')
        self.assertIn('喜欢防御流', session.calls[0]['messages'][1]['content'])
        self.assertNotIn('额外字段 viewer_memory', session.calls[0]['messages'][0]['content'])
        self.assertEqual(session.calls[0]['max_tokens'], self.config['brain']['max_tokens'])

    async def test_offline_and_unknown_viewers_do_not_write_live_profiles(self):
        dry = self.new_life(mode='dry-run')
        await dry.start('test')
        dry.heard({'kind': 'danmaku', 'uid': '2468179', 'name': '小明', 'text': '我喜欢防御流'})
        self.assertEqual(self.memory.viewers(), {})
        await self.life.start('test')
        await self.chat(uid='0')
        self.assertEqual(self.memory.viewers(), {})
        brain, session = self.brain(self.reply())
        brain.offline = True
        await brain.generate(SimpleNamespace(kind='chat', reply_uid='2468179', reply_text='我喜欢防御流'), {})
        self.assertEqual(session.calls, [])
        self.assertEqual(self.memory.viewers(), {})

    async def test_each_live_write_has_its_own_backup_even_with_identical_clock(self):
        await self.life.start('test')
        await self.chat()
        before = list((self.memory.dir / '备份').glob('*-熟人.md'))
        await self.chat(uid='9753108')
        after = list((self.memory.dir / '备份').glob('*-熟人.md'))
        self.assertEqual(len(after), len(before) + 1)
