import unittest
from host.config import load_config
from host.scheduler import Scheduler, ChatBatcher

class DirectChatTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        config = load_config()['brain']
        config.update(chat_reply_all=True, chat_user_replies_per_minute=3,
                      requests_per_minute=100, requests_per_hour=1000, min_gap_seconds=0)
        self.s = Scheduler(config, clock=lambda: self.now)
        self.b = ChatBatcher(self.s, social=object())
        self.ident = 0

    def add(self, uid='a'):
        self.ident += 1
        self.b.add(dict(id=str(self.ident), uid=uid, name='viewer', text='hello', kind='danmaku'))

    def test_three_per_user_and_independent_users(self):
        for _ in range(4): self.add()
        self.add('b')
        self.assertEqual(len(self.s.queue), 4)
        self.assertEqual([self.s.pop_ready().reply_uid for _ in range(4)], ['a','a','a','b'])
        self.now = 59.9
        self.add()
        self.assertEqual(len(self.s.queue), 0)
        self.now = 60
        self.add()
        self.assertEqual(self.s.pop_ready().reply_uid, 'a')

    def test_dispatch_window_and_no_expiry(self):
        for _ in range(3): self.add()
        self.now = 55
        for _ in range(3): self.assertIsNotNone(self.s.pop_ready())
        self.now = 60
        self.add()
        self.assertIsNone(self.s.pop_ready())
        self.now = 115
        self.assertIsNotNone(self.s.pop_ready())

    def test_global_budget_still_applies(self):
        self.s.c['requests_per_minute'] = 1
        self.add('a'); self.add('b')
        self.assertIsNotNone(self.s.pop_ready())
        self.assertIsNone(self.s.pop_ready())

    def test_queue_protects_accepted_replies(self):
        self.s.c['queue_size'] = 1
        self.add('a'); self.add('b')
        self.s.offer('urgent', priority=0)
        self.assertEqual(len(self.s.queue), 1)
        self.assertEqual(self.s.queue[0].reply_uid, 'a')
