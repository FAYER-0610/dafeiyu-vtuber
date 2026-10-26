"""Emotion contract tests using only local response stubs; no provider calls."""
import json
from types import SimpleNamespace
import unittest

from host.config import load_config
from host.providers import Brain
from host.safety import EMOTIONS, EMOTION_GUIDANCE, Safety

EXPECTED = {'neutral', 'happy', 'excited', 'surprised', 'sad', 'angry',
            'shy', 'smug', 'confused', 'cry', 'pout', 'starry', 'dizzy', 'playful'}


class StubResponse:
    status = 200

    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(self.value, ensure_ascii=False)}}]}


class StubSession:
    def __init__(self, value):
        self.value, self.calls = value, []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return StubResponse(self.value)


class EmotionTests(unittest.IsolatedAsyncioTestCase):
    def make_brain(self, value, config=None, offline=False):
        session = StubSession(value)
        secrets = {'DEEPSEEK_HOST_API_KEY': 'fake-local-secret-123456'}
        brain = Brain(session, secrets, config or load_config(), Safety(secrets), offline=offline)
        return brain, session

    def test_exact_fourteen_value_contract(self):
        self.assertEqual(EMOTIONS, EXPECTED)
        self.assertEqual(set(EMOTION_GUIDANCE), EXPECTED)
        self.assertEqual(len(EMOTIONS), 14)

    async def test_all_original_and_new_values_preserved(self):
        for emotion in sorted(EXPECTED):
            with self.subTest(emotion=emotion):
                brain, session = self.make_brain({'text': '小鲸鱼陪你稳稳爬塔。', 'emotion': emotion})
                result = await brain.generate(SimpleNamespace(text='一个安全的本地测试话题'), {})
                self.assertEqual(result['emotion'], emotion)
                self.assertEqual(len(session.calls), 1)  # A stub call, never a network request.

    async def test_invalid_values_fall_back_without_type_errors(self):
        for emotion in ['unknown', 'Shy', 'cry ', 'starry\n', '', None, True, 42, [], {}, ['happy']]:
            with self.subTest(emotion=emotion):
                brain, _ = self.make_brain({'text': '继续慢慢看尖塔。', 'emotion': emotion})
                result = await brain.generate(SimpleNamespace(text='本地测试'), {})
                self.assertEqual(result['emotion'], 'neutral')

    async def test_missing_emotion_falls_back(self):
        brain, _ = self.make_brain({'text': '继续慢慢看尖塔。'})
        result = await brain.generate(SimpleNamespace(text='本地测试'), {})
        self.assertEqual(result['emotion'], 'neutral')

    async def test_prompt_explains_every_scene_and_requires_evidence(self):
        brain, session = self.make_brain({'text': '暂时再观察一下。', 'emotion': 'confused'})
        await brain.generate(SimpleNamespace(text='战斗刚刚结束，结果还未确认。'), {'hp': 8, 'max_hp': 80})
        system = session.calls[0][1]['json']['messages'][0]['content']
        for name, scene in EMOTION_GUIDANCE.items():
            self.assertIn(f'{name}：{scene}', system)
        for rule in ['combat_ended仅代表战斗结束', '当前残血不等于刚刚一次掉了大量血',
                     '不得为了表情编造伤害、稀有度、操作效果或胜负', '不引导消费', '精确小写']:
            self.assertIn(rule, system)
        self.assertNotIn('fake-local-secret-123456', system)

    async def test_output_length_and_provider_settings_unchanged(self):
        config = load_config()
        config['brain']['max_text_chars'] = 12
        brain, session = self.make_brain({'text': '（挥手）第一句。第二句！第三句。', 'emotion': 'playful'}, config)
        result = await brain.generate(SimpleNamespace(text='本地测试'), {})
        self.assertLessEqual(len(result['text']), 12)
        self.assertNotIn('第三句', result['text'])
        self.assertNotIn('挥手', result['text'])
        payload = session.calls[0][1]['json']
        self.assertEqual(payload['model'], 'deepseek-chat')
        self.assertEqual(payload['max_tokens'], config['brain']['max_tokens'])
        self.assertEqual(payload['temperature'], config['brain']['temperature'])
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertFalse(payload['stream'])
        self.assertFalse(session.calls[0][1]['allow_redirects'])

    async def test_game_lines_are_one_short_sentence(self):
        long = '中毒八层还带力量四，这构装体下回合要是强化起来就难顶了。我得先算算这波怎么打。'
        brain, session = self.make_brain({'text': long, 'emotion': 'neutral'})
        result = await brain.generate(SimpleNamespace(text='牌局', kind='game'), {})
        self.assertLessEqual(len(result['text']), load_config()['brain']['game_text_chars'])
        self.assertNotIn('我得先算算', result['text'])                     # 只留第一句
        self.assertEqual(result['text'], '中毒八层还带力量四')                 # 超长退到逗号处，不切半个词
        self.assertIn('只说一句', session.calls[0][1]['json']['messages'][0]['content'])
        brain, _ = self.make_brain({'text': long, 'emotion': 'neutral'})
        chat = await brain.generate(SimpleNamespace(text='弹幕', kind='chat'), {})
        self.assertIn('我得先算算', chat['text'])                          # 回弹幕还能说两句

    async def test_chat_reply_calls_the_viewer_by_name(self):
        topic = SimpleNamespace(text='观众 小明 的弹幕：你好', kind='chat', reply_names=('小明',))
        brain, session = self.make_brain({'text': '你好呀，今天也来看我打牌啦。', 'emotion': 'happy'})
        result = await brain.generate(topic, {})
        self.assertTrue(result['text'].startswith('小明,你好呀'), result['text'])   # 漏了名字：句首补上
        payload = session.calls[0][1]['json']['messages']
        self.assertIn('必须原样叫出', payload[0]['content'])
        self.assertIn('小明', payload[1]['content'])
        brain, _ = self.make_brain({'text': '你好呀小明，坐下一起看。', 'emotion': 'happy'})
        self.assertTrue((await brain.generate(topic, {}))['text'].startswith('你好呀小明'))  # 已经叫了：不动
        two = SimpleNamespace(text='弹幕', kind='chat', reply_names=('小明', '【粉丝】阿花'))
        brain, _ = self.make_brain({'text': '谢谢支持！', 'emotion': 'happy', 'to': '阿花'})
        self.assertTrue((await brain.generate(two, {}))['text'].startswith('阿花,谢谢支持'))  # 按 to 补回的那位，去掉了粉丝牌括号
        brain, session = self.make_brain({'text': '先防一手', 'emotion': 'neutral'})
        game = await brain.generate(SimpleNamespace(text='牌局', kind='game', reply_names=('小明',)), {})
        self.assertNotIn('小明', game['text'])                                       # 牌局台词不叫人
        self.assertNotIn('必须原样叫出', session.calls[0][1]['json']['messages'][0]['content'])

    async def test_reply_hands_viewer_advice_to_the_board(self):
        heard = []
        topic = SimpleNamespace(text='观众 小明 的弹幕：先打左边那个', kind='chat', reply_names=('小明',))
        brain, session = self.make_brain({'text': '小明说先打左边，我想想。', 'emotion': 'neutral', 'advice': '先打左边那只敌人'})
        brain.on_advice = lambda name, text: heard.append((name, text))
        await brain.generate(topic, {})
        self.assertEqual(heard, [('小明', '先打左边那只敌人')])
        self.assertIn('advice', session.calls[0][1]['json']['messages'][0]['content'])
        brain, _ = self.make_brain({'text': '小明你好呀。', 'emotion': 'happy', 'advice': ''})
        brain.on_advice = lambda name, text: heard.append((name, text))
        await brain.generate(topic, {})
        brain, _ = self.make_brain({'text': '先防一手', 'emotion': 'neutral', 'advice': '乱出'})
        brain.on_advice = lambda name, text: heard.append((name, text))
        await brain.generate(SimpleNamespace(text='牌局', kind='game'), {})
        self.assertEqual(len(heard), 1)                                            # 闲聊、牌局台词都不算建议

    async def test_output_safety_still_filters_with_new_emotion(self):
        brain, _ = self.make_brain({'text': 'fake-local-secret-123456', 'emotion': 'cry'})
        result = await brain.generate(SimpleNamespace(text='本地测试'), {})
        self.assertNotIn('fake-local-secret', result['text'])
        self.assertEqual(result['emotion'], 'cry')
        self.assertEqual(result['text'], '这个不聊，看牌看牌。')

    async def test_offline_remains_valid_and_does_not_call_provider(self):
        brain, session = self.make_brain({}, offline=True)
        result = await brain.generate(SimpleNamespace(text='本地测试'), {})
        self.assertEqual(result['emotion'], 'happy')
        self.assertIn(result['emotion'], EMOTIONS)
        self.assertEqual(session.calls, [])


if __name__ == '__main__':
    unittest.main()
