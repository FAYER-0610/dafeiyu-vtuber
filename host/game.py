"""Read-only STS2 integration: hard allowlist, SSE + coalesced snapshots."""
import asyncio
import json
import logging
import re
import time
import aiohttp
from .scheduler import Gate

log = logging.getLogger('host.game')
ALLOWED_PATHS = {'/health', '/state', '/decisions', '/events/stream', '/data/monsters'}


def normalize_keys(value):
    if isinstance(value, list):
        return [normalize_keys(v) for v in value]
    if isinstance(value, dict):
        return {re.sub(r'(?<!^)(?=[A-Z])', '_', k).lower() if '_' not in k and not k.islower() else k.lower(): normalize_keys(v) for k, v in value.items()}
    return value


async def sse_frames(content):
    """Multi-line data, CRLF, comments; bounded frame. Bytes from aiohttp stream."""
    event, data, size = '', [], 0
    async for raw in content:
        line = raw.decode('utf-8-sig', errors='replace').rstrip('\r\n')
        if not line:
            if data:
                try:
                    payload = json.loads('\n'.join(data))
                    if isinstance(payload, dict):
                        yield event or payload.get('type', ''), payload
                except json.JSONDecodeError:
                    pass
            event, data, size = '', [], 0
        elif line.startswith('event:'):
            event = line[6:].strip()
        elif line.startswith('data:'):
            size += len(line)
            if size > 262144:
                raise ValueError('SSE frame too large')
            data.append(line[5:].lstrip(' '))


def project_state(state, health=None):
    state = normalize_keys(state)
    run, combat = state.get('run') or {}, state.get('combat') or {}
    players = run.get('players') or combat.get('players') or []
    local = next((p for p in players if p.get('is_local')), {})
    player = combat.get('player') or local or run
    hp = player.get('current_hp', run.get('current_hp'))
    mhp = player.get('max_hp', run.get('max_hp'))
    h = health or {}
    return {
        'run_id': state.get('run_id'), 'screen': state.get('screen', 'UNKNOWN'),
        'floor': run.get('floor'), 'character': local.get('character_name') or run.get('character_name') or local.get('character_id') or run.get('character_id'),
        'hp': hp, 'max_hp': mhp, 'turn': state.get('turn'),
        'teammate_online': bool(h.get('companion_process_alive')) or any(not p.get('is_local') and p.get('is_connected') for p in players),
        'play_running': bool(h.get('play_running')),
    }


SCREEN_NAMES = {
    'COMBAT': '战斗', 'MAP': '地图选路', 'REWARD': '战后奖励', 'SHOP': '商店', 'FAKE_MERCHANT': '商店', 'EVENT': '事件',
    'REST': '篝火', 'REST_SITE': '篝火', 'TREASURE': '宝箱', 'CHEST': '宝箱', 'CARD_SELECTION': '选牌',
    'GAME_OVER': '本局结束', 'MAIN_MENU': '主菜单', 'CHARACTER_SELECT': '选角色',
}
INTENTS = {'Attack': '攻击', 'Defend': '防御', 'Buff': '强化自己', 'Debuff': '给你上减益', 'StatusCard': '塞状态牌',
           'Heal': '回血', 'Escape': '逃跑', 'Sleep': '睡觉', 'Stun': '眩晕', 'Unknown': '意图不明'}


def _markup(text):
    # 游戏文本里的 [gold]…[/gold] 之类颜色标记对说话没用。
    return re.sub(r'\[/?[a-z_]+\]', '', str(text or '')).strip()


def _intent(i):
    kind = INTENTS.get(str(i.get('intent_type')), str(i.get('intent_type') or '?'))
    if i.get('damage') is not None:
        hits = i.get('hits') or 1
        return f'{kind}{i["damage"]}' + (f'×{hits}' if hits > 1 else '')
    if i.get('status_card_count'):
        return f'{kind}{i["status_card_count"]}张'
    return kind


# 保底解说没有新事件可说时，轮流挑一个角度看局面卡。
FILLER = {
    'COMBAT': ['手里这几张牌', '敌人这回合要干什么', '自己的血量和格挡', '这一仗打算怎么打', '卡组里哪张牌最想抽到'],
    'MAP': ['接下来想走哪条路', '现在这套卡组成型了没有', '这一幕还剩什么难关'],
}
FILLER_DEFAULT = ['现在这套卡组', '身上的遗物或药水', '这局到目前为止的感觉', '接下来最缺什么']
# 值得开口的动作；Mod 的先说后打和事后解说共用。
NARRATED = ('play_card', 'use_potion', 'choose_map_node', 'choose_reward_card', 'skip_reward_cards', 'select_deck_card',
            'buy_card', 'buy_relic', 'remove_card_at_shop', 'choose_event_option', 'choose_treasure_relic')
MOVES = {'use_potion': '用一瓶药水', 'choose_map_node': '选下一个房间', 'choose_reward_card': '从奖励里拿一张牌',
         'skip_reward_cards': '跳过这次的卡牌奖励', 'select_deck_card': '从卡组里挑一张牌', 'buy_card': '买一张牌',
         'buy_relic': '买一个遗物', 'remove_card_at_shop': '在商店删一张牌', 'choose_event_option': '选事件选项',
         'choose_treasure_relic': '拿宝箱里的遗物'}
# 关键操作。游戏 AI 的思路多半是英文。斩杀是一场战斗最该说的一句，不受战斗台词间隔限制；
# “打不死”“can't kill”这种否定说法不算。
# 只认明确的说法：单独一个 kill（“要尽快 kill 它”）或“打死”（“别被打死”）都太含糊。
LETHAL = re.compile(r'斩杀|收掉|\b(lethal|kills (it|him|her|them)|finish(es)? (it|him|her|them) off)\b', re.I)
NOT_LETHAL = re.compile(r"(打不死|杀不掉|\b(can'?t|cannot|won'?t|not|no|isn'?t)\s+(\w+\s+){0,2}(lethal|kill))", re.I)
KEY_MOVE = re.compile(r'致命|关键|保命|\b(surviv\w*|dying|would die)\b', re.I)
GATE_START, GATE_TOTAL = 5, 10  # 秒：多久内得开始想这句（前面有话在说就等着），整步最多让游戏等多久；Mod 那边上限 20 秒
GATE_FRESH = 600  # 这么久内 Mod 来问过，就认为先说后打在工作，不再做事后解说

NO_RUN = ('', 'UNKNOWN', 'MAIN_MENU', 'CHARACTER_SELECT', 'GAME_OVER')


class GameTopics:
    def __init__(self, scheduler, safety, config, clock=time.monotonic):
        self.scheduler, self.safety, self.c, self.clock = scheduler, safety, config, clock
        self.previous = {}
        self.last_decision = float('-inf')
        self.decision_ids = set()
        self.last_map = {}
        self.current_state = {}
        self.monsters = {}
        self.filler_turn = 0
        self.last_gate = float('-inf')
        self.last_combat_line = float('-inf')
        self.planned_turn = None
        self.guidance = None                    # 观众建议板（app 接上）；思路里点了名就说一句听没听
        self.answered = set()
        self.viewer = None
        self.hook = lambda kind, **data: None   # lifecycle 接上后：心情 + 当场记事

    def offer(self, text, priority=25, key=None):
        # 牌局话题要趁热说：排队太久就作废；关键时刻（优先级≤7）用常规时效。
        if self.safety.classify(text) == 'safe':
            self.scheduler.offer(text, 'game', priority, key, None if priority <= 7 else self.c['topic_ttl_seconds'],
                                 screen=str(self.current_state.get('screen') or '') or None)

    def update(self, state):
        state = normalize_keys(state)
        old = self.previous
        current = project_state(state)
        run_id = current['run_id']
        if run_id != old.get('run_id'):
            self.last_map = {}
            self.decision_ids.clear()
            # Never narrate queued events from a previous run after a restart/menu transition.
            import heapq
            self.scheduler.queue = [t for t in self.scheduler.queue if t.kind != 'game']
            heapq.heapify(self.scheduler.queue)
            if run_id:
                self.hook('run', character=current['character'])
        self.current_state = state
        if state.get('map'):
            self.last_map = state['map']
        floor = current['floor']
        if floor is not None and (floor, run_id) != (old.get('floor'), old.get('run_id')):
            self.hook('floor', floor=floor)  # 上一层不单独说，开打时自然会提
        screen = current['screen']
        old_screen = old.get('screen')
        if screen != old_screen:
            if screen == 'COMBAT':
                self.combat_start(state)
            elif old_screen == 'COMBAT' and screen == 'MAP':
                self.offer('你这场战斗打完了，进入战后阶段。只有明确看到奖励才能判断胜利，不要编造战果。', 12, f'combat-end:{run_id}:{floor}')
            if old_screen == 'COMBAT':
                self.hook('combat_end', floor=floor)
            if screen in ('SHOP', 'FAKE_MERCHANT'):
                gold = (state.get('run') or {}).get('gold', '未知')
                self.offer(f'你进了商店，手里有 {gold} 金币。', 30, f'shop:{run_id}:{floor}')
            if screen == 'EVENT':
                title = self.safety.public_text((state.get('event') or {}).get('title', '未知事件'), 60, '未知事件')
                self.offer(f'你走进事件房，事件名：{title}。没有结果前不要预言选项收益。', 30, f'event:{run_id}:{floor}')
        # 战后结算是一个画面一句话：打完了、奖励、选卡候选合成一条，选卡时先说后打那句再讲选了什么。
        reward = state.get('reward') or {}
        cards = tuple(str(card.get('name') or card.get('card_id') or '未知卡') for card in reward.get('card_options', []))
        if screen == 'REWARD' and screen != old_screen:
            ended = '这场仗打完了，' if old_screen == 'COMBAT' else ''
            picks = f'选卡候选：{"、".join(cards[:6])}，还没选定。' if cards else ''
            self.offer(f'{ended}你到了战后奖励阶段。可见奖励：' + self.safety.public_text(json.dumps(reward, ensure_ascii=False), 450, '待选择')
                       + f'。{picks}说一句反应就行，别编造选择结果和战果。', 12 if ended else 25, f'reward:{run_id}:{floor}')
        # Reward card-choice is a substate of REWARD, not necessarily a screen change.
        elif cards and (cards != old.get('_reward_cards') or run_id != old.get('run_id')):
            self.offer('你在挑卡牌奖励，当前候选：' + '、'.join(cards[:6]) + '。还没选定，不要编造选择结果。',
                       23, f'reward-cards:{run_id}:{floor}:{cards}')
        current['_reward_cards'] = cards
        # game_over may become populated one snapshot after screen transition.
        over = state.get('game_over') or {}
        ended = screen == 'GAME_OVER' and 'is_victory' in over
        if ended:
            won = over['is_victory']
            self.offer('你这把通关成功了！' if won else '这把你打输了，角色倒下了。可以不甘心、可以嘴硬，但别甩锅给观众，也别自暴自弃。', 0,
                       f'over:{run_id}:{won}')
            if not old.get('_over'):
                self.hook('over', won=bool(won), floor=floor)
        current['_over'] = ended
        hp, maximum = current['hp'], current['max_hp']
        low = isinstance(hp, (int, float)) and isinstance(maximum, (int, float)) and maximum > 0 and 0 < hp / maximum <= self.c['low_hp_ratio']
        prev_low = old.get('_low', False)
        if low and (not prev_low or run_id != old.get('run_id')):
            self.offer(f'你残血了！生命只剩 {hp}/{maximum}，紧张一下，但别乱了阵脚。', 5, f'low:{run_id}:{floor}')
            self.hook('low', hp=hp, max_hp=maximum, floor=floor)
        current['_low'] = low
        self.previous = current
        return {k: v for k, v in current.items() if not k.startswith('_')}

    def brief(self):
        """她说话时看到的“局面卡”：从最新快照里挑说牌需要的东西，控制长度。只读、只给模型看。"""
        state = self.current_state
        if not state:
            return {'画面': '还没连上游戏'}
        view = state.get('agent_view') or {}
        run, vrun = state.get('run') or {}, view.get('run') or {}
        combat, vcombat = state.get('combat') or {}, view.get('combat') or {}
        clean = lambda text, limit=90: self.safety.public_text(_markup(text), limit)
        card = {'画面': SCREEN_NAMES.get(str(state.get('screen')), str(state.get('screen') or '未知'))}
        if run:
            card['第几层'] = run.get('floor')
            card['我'] = (f'{run.get("character_name") or "?"}，{run.get("current_hp")}/{run.get("max_hp")}血，'
                         f'{run.get("gold", "?")}金币' + (f'，进阶{run["ascension"]}' if run.get('ascension') else ''))
        if combat:
            me = combat.get('player') or {}
            powers = '、'.join(f'{x.get("name")}{x.get("amount") or ""}' for x in me.get('powers') or [] if x.get('name'))
            card['回合'] = state.get('turn')
            card['我这回合'] = (f'{me.get("current_hp")}/{me.get("max_hp")}血，格挡{me.get("block", 0)}，'
                              f'能量{me.get("energy")}/{run.get("max_energy", "?")}' + (f'，状态：{powers}' if powers else ''))
            hand = vcombat.get('hand') or []
            cards = [clean(c.get('line') or c.get('name')) for c in hand[:10]] if hand else \
                [clean(f'{c.get("name")} [{c.get("energy_cost")}费]：{c.get("resolved_rules_text") or ""}') for c in (combat.get('hand') or [])[:10]]
            if cards:  # 开打那一瞬间快照里手牌还是空的（游戏正在自动发牌）：不给空列表，免得她说“还没摸牌”
                card['手牌'] = cards
            foes = []
            for e in combat.get('enemies') or []:
                if not e.get('is_alive', True):
                    continue
                plan = '、'.join(_intent(i) for i in e.get('intents') or []) or '未知'
                buffs = '、'.join(f'{x.get("name")}{x.get("amount") or ""}' for x in e.get('powers') or [] if x.get('name'))
                hp, top = e.get('current_hp'), e.get('max_hp')
                dying = isinstance(hp, int) and isinstance(top, int) and hp <= max(10, top // 10)
                foes.append(clean(f'{e.get("name")} {hp}/{top}血' + ('（快死了）' if dying else '') + f'，格挡{e.get("block", 0)}，'
                                  f'这回合要{plan}' + (f'，状态：{buffs}' if buffs else ''), 120))
            card['敌人'] = foes
            piles = vrun.get('piles') or {}
            card['牌堆'] = f'抽牌堆{len(piles.get("draw") or vcombat.get("draw") or [])}张，弃牌堆{len(piles.get("discard") or vcombat.get("discard") or [])}张'
            if combat.get('end_turn_will_kill_player'):
                card['危险'] = '现在直接结束回合会死'
        relics = [_markup(r.get('name')) for r in run.get('relics') or [] if r.get('name')]
        if relics:
            card['遗物'] = '、'.join(relics[:15])
        potions = [p.get('name') for p in run.get('potions') or [] if p.get('name')]
        card['药水'] = '、'.join(potions) or '没有'
        deck = vrun.get('deck') or []
        if deck:
            card['卡组'] = clean('、'.join(_markup(str(c.get('line', '')).split(' [')[0]) for c in deck[:25]), 400)
        event = state.get('event') or {}
        if event.get('title'):
            card['事件'] = clean(event['title'], 40)
        return card

    def filler(self):
        """保底解说的话题：在一局里才有，按画面轮换角度；不在局里返回 None。"""
        state = self.current_state or {}
        screen = str(state.get('screen') or '')
        if not state.get('run') or screen in NO_RUN:
            return None
        if screen == 'COMBAT' and self.clock() - self.last_gate < GATE_FRESH:
            return None  # 先说后打在工作时，战斗里每回合开头已经会说打算，不再硬凑
        aspects = FILLER.get(screen, FILLER_DEFAULT)
        aspect = aspects[self.filler_turn % len(aspects)]
        self.filler_turn += 1
        return f'边打边自言自语一句，说说{aspect}。从局面卡里挑一个具体的点，带点态度；别报一串数字，别重复刚才说过的话。'

    def combat_start(self, state):
        run = state.get('run') or {}
        combat = state.get('combat') or {}
        enemies = [str(e.get('name') or e.get('enemy_id') or '未知敌人') for e in combat.get('enemies', [])]
        room_type = combat.get('room_type') or run.get('room_type') or ''
        # Cached MAP current_node is the PREVIOUS room, not the new encounter.
        game_map = state.get('map') or {}
        node = game_map.get('current_node') or {}
        for n in game_map.get('nodes', []):
            if node and n.get('row') == node.get('row') and n.get('col') == node.get('col'):
                room_type = n.get('node_type', room_type)
        boss = run.get('boss_id')
        if boss and any(e.get('enemy_id') == boss for e in combat.get('enemies', [])):
            room_type = 'Boss'
        classified = False
        if not room_type:
            enemy_types = [self.monsters.get(e.get('enemy_id'), '').lower() for e in combat.get('enemies', [])]
            if 'boss' in enemy_types or 'elite' in enemy_types:
                room_type = 'Boss' if 'boss' in enemy_types else 'Elite'
                classified = True
        special = room_type.lower() in ('boss', 'elite')
        label = {'boss': 'Boss 战', 'elite': '精英战'}.get(room_type.lower(), '战斗（类型未确认，不要猜成精英或Boss）')
        if classified:
            label = f'遇到了游戏怪物资料标为 {room_type} 级的敌人（依据怪物类型，不是房间的直接标记）'
        self.offer(f'你开战了：{label}，对面是{"、".join(enemies[:3]) or "还没看清的敌人"}。说一句开打时的反应就行，不用报敌人的数据，也别提手牌（开打时游戏会自动发好牌）。', 7 if special else 20,
                   f'combat:{state.get("run_id")}:{run.get("floor")}')
        self.hook('combat', room=room_type if special else '', floor=run.get('floor'), enemies='、'.join(enemies[:4]))

    def event(self, kind, envelope):
        data = normalize_keys(envelope.get('data') or {})
        if kind == 'decision_made':
            self.decision(data)
        elif kind == 'event_state_changed' and self.clock() - self.last_gate >= GATE_FRESH:
            # 先说后打在工作时，事件里每个选择出手前已经说过了，不再补一句“有新进展”。
            self.offer('事件出现了新的进展，等待当前画面确认具体结果，不编造。', 35,
                       f'event-change:{self.current_state.get("run_id")}:{(self.current_state.get("run") or {}).get("floor")}')

    def turn_key(self):
        state = self.current_state or {}
        return (state.get('run_id'), (state.get('run') or {}).get('floor'), state.get('turn'))

    def worth(self, action, reason, turn_start=False):
        """这一步值不值得说：'lethal' 斩杀 / 'key' 保命这类关键操作 / 'plan' 回合开头的打算 / 'normal' 普通决定 / None 不说。

        战斗里像真人主播：每回合第一张牌前说一句打算，保命这种关键操作再说一句，其余出牌不说；
        两句战斗台词至少隔 combat_gap 秒，只有斩杀不受这个限制。选卡、选路、买东西、选事件这类决定按 decision_cooldown_seconds 冷却。
        游戏 AI 的思路常常是英文，关键词中英都认。
        """
        if action not in NARRATED or not reason or self.safety.classify(reason) != 'safe':
            return None
        now = self.clock()
        # 打牌的她回应了观众建议（思路里点了名）：说一句听没听，让观众知道自己的话有用。每条建议只说一次。
        self.viewer = None
        board = self.guidance.snapshot()['items'] if self.guidance else []
        for item in board:
            key = (item['name'], item['text'])
            if item['name'] in reason and key not in self.answered:
                self.answered.add(key)
                self.viewer = item['name']
                self.last_combat_line = now
                return 'viewer'
        if action in ('play_card', 'use_potion'):
            if LETHAL.search(reason) and not NOT_LETHAL.search(reason):
                self.last_combat_line = now
                return 'lethal'
            kind = 'key' if KEY_MOVE.search(reason) else 'plan' if turn_start else None
            if not kind or now - self.last_combat_line < self.c.get('combat_gap_seconds', 20):
                return None
            self.last_combat_line = now
            return kind
        if now - self.last_decision < self.c['decision_cooldown_seconds']:
            return None
        self.last_decision = now
        return 'normal'

    def decision(self, data):
        """事后解说（Mod 没开先说后打时的退路）：从 /decisions 读到已经执行的操作。"""
        key = data.get('id')
        if key in self.decision_ids:
            return
        self.decision_ids.add(key)
        if len(self.decision_ids) > 1000:
            self.decision_ids = {key}
        if self.clock() - self.last_gate < GATE_FRESH:
            return  # 先说后打在工作，这一步出手前已经问过了
        action, reason = data.get('action', ''), data.get('reason') or ''
        worth = self.worth(action, reason)
        if worth:
            self.offer(f'你刚刚执行了 {action}，你当时记下的思路是：{reason[:450]}。用第一人称一句话讲这一步的想法，只基于这段思路，不补充没出现的卡名。',
                       22 if worth == 'key' else 38, f'decision:{key}')

    def move(self, action, card_index=None, target_index=None):
        """把 Mod 发来的动作翻成人话；出牌时从当前快照里找牌名和目标。"""
        combat = self.current_state.get('combat') or {}
        hand = combat.get('hand') or []
        if action == 'play_card' and isinstance(card_index, int) and 0 <= card_index < len(hand):
            text = f'打出「{_markup(hand[card_index].get("name") or "这张牌")}」'
            foes = combat.get('enemies') or []
            if isinstance(target_index, int) and 0 <= target_index < len(foes) and foes[target_index].get('name'):
                text += f'，打{_markup(foes[target_index]["name"])}'
            return self.safety.public_text(text, 60)
        return MOVES.get(action, action)

    async def narrate(self, payload):
        """先说后打：Mod 执行一步前来问。值得说就排到最前面，等她说完再回；否则立刻回。返回她说没说。"""
        self.last_gate = self.clock()
        action, reason = str(payload.get('action') or ''), str(payload.get('reason') or '')[:450]
        turn = self.turn_key()
        turn_start = action in ('play_card', 'use_potion') and turn != self.planned_turn
        if turn_start:
            self.planned_turn = turn  # 这回合的第一步：说不说都算过了，同一回合不再说打算
        worth = self.worth(action, reason, turn_start)
        if not worth:
            return False
        what = self.move(action, payload.get('card_index'), payload.get('target_index'))
        if worth == 'viewer':
            text = (f'你正要{what}，你的思路是：{reason}。这一步和观众{self.viewer}的建议有关：动手之前用第一人称说一句，'
                    f'叫出{self.viewer}的名字，说你听了他的还是没听，说完就出手。只基于这段思路，不补充没出现的卡名。')
        elif worth == 'plan':
            text = (f'新的回合，你已经想好这回合整套怎么打：{reason}。第一步是{what}。动手之前用第一人称说一句这回合的打算'
                    f'（先防还是先打、为什么），说完就出手。中途抽到新牌你会重新想，所以别把话说死：'
                    f'只说这回合，不预言下回合会怎样，也不断言敌人这回合死不了。只基于这段思路和局面卡，不补充没出现的卡名。')
        elif worth == 'lethal':
            text = (f'你正要{what}，这一下就能把它打死，你的思路是：{reason}。动手之前用第一人称说一句收掉它的话，'
                    f'干脆、带点得意，说完就出手。只基于这段思路，不补充没出现的卡名。')
        else:
            text = (f'你正要{what}，你的思路是：{reason}。动手之前先用第一人称说一句你要干什么、为什么，'
                    f'像边想边说出口，说完就出手。只基于这段思路，不补充没出现的卡名。')
        if self.safety.classify(text) != 'safe':
            return False
        screen = self.current_state.get('screen')
        stale = [t for t in self.scheduler.queue if t.kind == 'game' and not t.gate and t.priority > 7 and t.screen == screen]
        if stale:
            # 她马上要讲这一步：排着队的、讲同一个画面的旧话题就不念了，免得一件事说好几遍。
            import heapq
            self.scheduler.queue = [t for t in self.scheduler.queue if t not in stale]
            heapq.heapify(self.scheduler.queue)
        gate = Gate()
        if not self.scheduler.offer(text, 'game', 1, f'gate:{time.monotonic()}', ttl=GATE_START, gate=gate, screen=screen):
            return False
        started = time.monotonic()
        try:
            await asyncio.wait_for(gate.started.wait(), GATE_START)
        except asyncio.TimeoutError:
            self.scheduler.cancel(gate)  # 前面那句太长、或者限额满了：这一步不说，别让游戏干等
            log.info('Narrate %s skipped: not started within %ss', action, GATE_START)
            return False
        try:
            await asyncio.wait_for(gate.done.wait(), max(1, GATE_TOTAL - (time.monotonic() - started)))
        except asyncio.TimeoutError:
            pass
        log.info('Narrate %s: game held %.1fs', action, time.monotonic() - started)
        return True


class GameReader:
    def __init__(self, session, base_url, topics, hub, config):
        self.session, self.url, self.topics, self.hub, self.c = session, base_url.rstrip('/'), topics, hub, config
        self.refresh = asyncio.Event()
        self.last_process = None
        self.first_decisions = True
        self.last_decision_poll = 0

    async def get(self, path, params=None):
        if path not in ALLOWED_PATHS or path == '/events/stream':
            raise ValueError('Read-only game allowlist violation')
        async with self.session.get(self.url + path, params=params, timeout=aiohttp.ClientTimeout(total=5), allow_redirects=False) as r:
            r.raise_for_status()
            body = await r.json()
            if not body.get('ok'):
                raise ValueError('Game API not ready')
            return normalize_keys(body['data'])

    async def snapshots(self):
        while True:
            try:
                health = await self.get('/health')
                if health.get('service') != 'sts2-ai-agent':
                    raise ValueError('Wrong local game service')
                if health.get('process_id') != self.last_process:
                    self.last_process = health.get('process_id')
                    self.first_decisions = True
                    self.topics.decision_ids.clear()
                    try:
                        monsters = await self.get('/data/monsters')
                        self.topics.monsters = {m['id']: m.get('type', '') for m in monsters}
                    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
                        self.topics.monsters = {}
                state = await self.get('/state')
                self.topics.update(state)
                projection = project_state(state, health)
                # Treat all displayable game strings as untrusted metadata too.
                for k, v in projection.items():
                    if isinstance(v, str):
                        projection[k] = self.topics.safety.public_text(v, 80, '未知')
                await self.hub.status_update(game_online=True, game=projection)
                if time.monotonic() - self.last_decision_poll > 20:
                    rows = await self.get('/decisions', {'limit': 10})
                    if self.first_decisions:
                        self.topics.decision_ids.update(d.get('id') for d in rows)
                        self.first_decisions = False
                    else:
                        for row in rows:
                            if row.get('run_id') == state.get('run_id'):
                                self.topics.decision(row)
                    self.last_decision_poll = time.monotonic()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as exc:
                await self.hub.status_update(game_online=False, game={**self.hub.status['game'], 'teammate_online': False, 'play_running': False})
                log.warning('Game snapshot unavailable (%s); reconnecting', type(exc).__name__)
            self.refresh.clear()
            try:
                await asyncio.wait_for(self.refresh.wait(), self.c['snapshot_seconds'])
                await asyncio.sleep(0.6)  # coalesce rapid turns; never poll full state per card
            except asyncio.TimeoutError:
                pass

    async def stream(self):
        while True:
            try:
                async with self.session.get(self.url + '/events/stream', timeout=aiohttp.ClientTimeout(total=None, sock_read=40), allow_redirects=False) as response:
                    response.raise_for_status()
                    if 'text/event-stream' not in response.headers.get('Content-Type', ''):
                        raise ValueError('Expected SSE')
                    await self.hub.status_update(game_stream=True)
                    self.refresh.set()
                    async for kind, envelope in sse_frames(response.content):
                        self.topics.event(kind, envelope)
                        if kind in ('stream_ready', 'session_started', 'combat_started', 'combat_ended', 'screen_changed', 'reward_decision_required'):
                            self.refresh.set()
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError) as exc:
                log.warning('Game SSE disconnected (%s)', type(exc).__name__)
            await self.hub.status_update(game_stream=False)
            await asyncio.sleep(self.c['reconnect_seconds'])
