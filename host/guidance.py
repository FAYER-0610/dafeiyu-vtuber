"""观众的打法建议：不是排队执行的指令，而是摆在打牌那部分的她面前的“最近大家怎么说”。

Mod 每次决策前来 GET /api/guidance 读一眼，自己权衡要不要听。主播程序不命令游戏，只是让她看得见弹幕。
"""
import time
from collections import deque


class Guidance:
    def __init__(self, config=None, clock=time.monotonic):
        c = config or {}
        self.window = c.get('guidance_seconds', 90)          # 一条建议在她面前摆多久
        self.keep = c.get('guidance_max_items', 3)            # 同时最多摆几条
        self.gap = c.get('guidance_gap_seconds', 20)          # 全场多久收一条
        self.per_user = c.get('guidance_user_seconds', 60)    # 同一个人多久收一条
        self.clock = clock
        self.items = deque()
        self.users = {}
        self.last = float('-inf')
        self.version = 0

    def add(self, name, text):
        """收下一条建议；限流挡掉就返回 False。"""
        now = self.clock()
        if now - self.last < self.gap or now - self.users.get(name, float('-inf')) < self.per_user:
            return False
        self.last = self.users[name] = now
        self.users = {k: t for k, t in self.users.items() if now - t < self.per_user}
        self.items.append((now, name, text))
        while len(self.items) > self.keep:
            self.items.popleft()
        self.version += 1
        return True

    def snapshot(self):
        now = self.clock()
        while self.items and now - self.items[0][0] > self.window:
            self.items.popleft()
        return {'version': self.version,
                'items': [{'name': name, 'text': text, 'age': int(now - at)} for at, name, text in self.items]}
