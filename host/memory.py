"""大肥鱼的长期记忆：memory/ 下的 Markdown，用户随时可以打开改。

程序在下播整理时写入；正式直播中，熟人档案还会随来访和聊天当场更新。写前把旧文件备份到 memory/备份/ 并记一行修改记录；
每次都是“读最新文件 → 改 → 原子写回”，用户手改的内容不会被整块覆盖。
角色卡.md 只读，程序永远不写。
"""
from datetime import datetime
import os
from pathlib import Path
import re
import uuid
from .config import ROOT

CARD = '角色卡.md'
ABOUT, VIEWERS, MEMES, DIARY, BACKUP = '关于我.md', '熟人.md', '梗.md', '日记', '备份'
MAX_BACKUPS = 300

TEMPLATES = {
    ABOUT: '# 关于我\n\n'
           '<!-- 大肥鱼对自己和这个直播间的长期记忆。“数据”每次下播由程序更新，数字改了也会被沿用；\n'
           '     “我记得的事”是她下播后自己补的，你可以随便改、删、加。 -->\n\n'
           '## 数据\n- 第一次开播：\n- 已播场次：0\n- 累计时长：0 分钟\n- 最远打到：第 0 层\n- 通关次数：0\n\n'
           '## 我记得的事\n',
    VIEWERS: '# 熟人\n\n'
             '<!-- 在直播间说过话的观众。每人一节，标题是昵称；印象在聊天中更新，下播再整理，你可以直接改。\n'
             '     删掉整节就等于忘了这个人。只记昵称、uid 和她的印象，不记别的个人信息。 -->\n',
    MEMES: '# 直播间的梗\n\n<!-- 一行一个：“- 梗：意思”。她会偶尔拿来用，不想要的直接删。 -->\n',
}


def diary_order(path):
    # 2026-10-25.md < 2026-10-25-2.md：按数字排，不按字符排。
    return tuple(int(n) for n in re.findall(r'\d+', path.stem))


def _clean(text, limit):
    # One line, no Markdown control characters: memory text never becomes structure.
    text = re.sub(r'\s+', ' ', str(text)).strip()
    return re.sub(r'[#<>`|]', '', text)[:limit].strip()


class Memory:
    def __init__(self, directory=None, clock=datetime.now):
        self.dir = Path(directory or ROOT / 'memory')
        self.clock = clock
        self.cache = {}

    # ---------- 读 ----------
    def read(self, name):
        path = self.dir / name
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return TEMPLATES.get(name, '')
        hit = self.cache.get(name)
        if hit and hit[0] == mtime:
            return hit[1]
        try:
            text = path.read_text(encoding='utf-8-sig')
        except (OSError, UnicodeDecodeError):
            return hit[1] if hit else TEMPLATES.get(name, '')
        self.cache[name] = (mtime, text)
        return text

    @staticmethod
    def strip_comments(text):
        return re.sub(r'<!--.*?-->', '', text, flags=re.S)

    def section(self, name, title):
        text = self.strip_comments(self.read(name))
        match = re.search(rf'^##\s*{re.escape(title)}\s*$(.*?)(?=^##\s|\Z)', text, flags=re.M | re.S)
        return match.group(1).strip() if match else ''

    def bullets(self, name, title=None):
        body = self.section(name, title) if title else self.strip_comments(self.read(name))
        return [line[1:].strip() for line in body.splitlines() if line.startswith('-') and line[1:].strip()]

    def stats(self):
        values = {}
        for line in self.bullets(ABOUT, '数据'):
            key, _, value = line.partition('：')
            values[key.strip()] = value.strip()
        def number(key):
            found = re.search(r'\d+', values.get(key, ''))
            return int(found.group()) if found else 0
        return {'first': values.get('第一次开播', ''), 'streams': number('已播场次'), 'minutes': number('累计时长'),
                'best_floor': number('最远打到'), 'wins': number('通关次数')}

    def viewers(self):
        """{uid: {'name', '外号', '来过', '第一次见', '最近一次', '印象'}}，解析失败的节直接跳过。"""
        people = {}
        text = self.strip_comments(self.read(VIEWERS))
        for block in re.split(r'^##\s+', text, flags=re.M)[1:]:
            lines = block.splitlines()
            entry = {'name': lines[0].strip()}
            for line in lines[1:]:
                key, sep, value = line.lstrip('- ').partition('：')
                if sep:
                    entry[key.strip()] = value.strip()
            uid = entry.get('uid', '')
            if uid.isdigit():
                people[uid] = entry
        return people

    def viewer_note(self, uid):
        entry = self.viewers().get(str(uid))
        if not entry:
            return None
        parts = [f'外号{entry["外号"]}' if entry.get('外号') else '', f'来过{entry["来过"]}' if entry.get('来过') else '',
                 entry.get('印象', '')]
        return _clean('，'.join(p for p in parts if p), 120)

    def last_diary(self):
        folder = self.dir / DIARY
        files = sorted(folder.glob('*.md'), key=diary_order) if folder.is_dir() else []
        if not files:
            return None
        body = self.strip_comments(self.read(f'{DIARY}/{files[-1].name}'))
        body = re.split(r'^##\s*动态', body, flags=re.M)[0]
        body = '\n'.join(line for line in body.splitlines() if not line.startswith('#')).strip()
        return {'date': files[-1].stem, 'text': _clean(body, 400)}

    # ---------- 写 ----------
    def write(self, name, text, why):
        path = self.dir / name
        if name == CARD or not path.resolve().is_relative_to(self.dir.resolve()):
            raise ValueError('Refusing to write this memory file')
        path.parent.mkdir(parents=True, exist_ok=True)
        old = path.read_text(encoding='utf-8-sig') if path.exists() else None
        if old == text:
            return
        # 直播中一秒内可能写好几次：带上微秒和随机串，每次写入都有自己的备份。
        stamp = f'{self.clock():%Y%m%d-%H%M%S-%f}-{uuid.uuid4().hex[:8]}'
        backup = self.dir / BACKUP
        backup.mkdir(exist_ok=True)
        if old is not None:
            (backup / f'{stamp}-{name.replace("/", "-")}').write_text(old, encoding='utf-8')
            for stale in sorted(p for p in backup.iterdir() if p.name != '修改记录.md')[:-MAX_BACKUPS]:
                stale.unlink(missing_ok=True)
        with open(backup / '修改记录.md', 'a', encoding='utf-8') as log:
            log.write(f'- {self.clock():%Y-%m-%d %H:%M} {name}：{why}\n')
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(text, encoding='utf-8')
        os.replace(tmp, path)
        self.cache.pop(name, None)

    def ensure(self):
        for name, text in TEMPLATES.items():
            if not (self.dir / name).exists():
                self.write(name, text, '新建')

    def _replace_section(self, text, title, body):
        pattern = rf'(^##\s*{re.escape(title)}\s*$\n)(.*?)(?=^##\s|\Z)'
        if re.search(pattern, text, flags=re.M | re.S):
            return re.sub(pattern, lambda m: m.group(1) + body.rstrip('\n') + '\n\n', text, count=1, flags=re.M | re.S)
        return text.rstrip('\n') + f'\n\n## {title}\n{body}'

    def save_stats(self, stats, why):
        text = self.read(ABOUT) or TEMPLATES[ABOUT]
        body = (f'- 第一次开播：{stats["first"]}\n- 已播场次：{stats["streams"]}\n'
                f'- 累计时长：{stats["minutes"]} 分钟\n- 最远打到：第 {stats["best_floor"]} 层\n- 通关次数：{stats["wins"]}\n')
        self.write(ABOUT, self._replace_section(text, '数据', body), why)

    def remember(self, items, why):
        items = [_clean(x, 60) for x in items if _clean(x, 60)]
        if not items:
            return
        text = self.read(ABOUT) or TEMPLATES[ABOUT]
        existing = self.bullets(ABOUT, '我记得的事')
        body = ''.join(f'- {x}\n' for x in existing + [x for x in items if x not in existing])
        self.write(ABOUT, self._replace_section(text, '我记得的事', body), why)

    def add_memes(self, memes, why):
        text = self.read(MEMES) or TEMPLATES[MEMES]
        known = {line.partition('：')[0] for line in self.bullets(MEMES)}
        new = []
        for n, m in ((_clean(n, 16), _clean(m, 50)) for n, m in memes):
            if n and m and n not in known:
                known.add(n)
                new.append((n, m))
        if new:
            self.write(MEMES, text.rstrip('\n') + '\n' + ''.join(f'- {n}：{m}\n' for n, m in new), why)

    def _viewer_blocks(self):
        text = self.read(VIEWERS) or TEMPLATES[VIEWERS]
        head, *blocks = re.split(r'^(?=##\s)', text, flags=re.M)
        index = {}
        for i, block in enumerate(blocks):
            found = re.search(r'^-\s*uid：\s*(\d+)\s*$', block, flags=re.M)
            if found:
                index[found.group(1)] = i
        return head, blocks, index

    @staticmethod
    def _set_field(block, key, value):
        line = f'- {key}：{value}'
        if re.search(rf'^-\s*{key}：.*$', block, flags=re.M):
            return re.sub(rf'^-\s*{key}：.*$', lambda _: line, block, count=1, flags=re.M)
        return block.rstrip('\n') + '\n' + line + '\n'

    def remember_viewer(self, uid, impression, before, why):
        """直播中聊出的新印象：只改这位观众的“印象”一行。

        before 是发请求前读到的档案：请求期间用户手改了印象就不覆盖；整节被删了就不重建。
        """
        head, blocks, index = self._viewer_blocks()
        uid = str(uid)
        if uid not in index:
            return False
        block = blocks[index[uid]]
        found = re.search(r'^-\s*印象：(.*)$', block, flags=re.M)
        current = found.group(1).strip() if found else ''
        if current != ((before or {}).get('印象') or '').strip():
            return False
        impression = _clean(impression, 60)
        if not impression or impression == current:
            return False
        blocks[index[uid]] = self._set_field(block, '印象', impression).rstrip('\n') + '\n\n'
        self.write(VIEWERS, head.rstrip('\n') + '\n\n' + ''.join(blocks), why)
        return True

    def update_viewers(self, visits, notes, why, count_visit=True, session=None):
        """visits: {uid: name} 本场说过话的人；notes: {uid: {'外号', '印象'}} 她的新印象（可空）。

        session 是这场直播的场次标记：档案上已经标着这一场，就不再多算一次来访（直播中已经记过、程序重启接着记）。
        count_visit=False 只补印象，不动来访次数。
        """
        today = f'{self.clock():%Y-%m-%d}'
        head, blocks, index = self._viewer_blocks()
        set_field = self._set_field
        for uid, name in visits.items():
            uid, name = str(uid), _clean(name, 24) or '观众'
            note = notes.get(uid) or {}
            if uid in index:
                block = blocks[index[uid]]
                marked = re.search(r'^-\s*场次标记：\s*(\S+)', block, flags=re.M)
                if count_visit and not (session and marked and marked.group(1) == session):
                    count = re.search(r'^-\s*来过：\s*(\d+)', block, flags=re.M)
                    block = set_field(block, '来过', f'{int(count.group(1)) + 1 if count else 1} 场')
                    block = set_field(block, '最近一次', today)
            else:
                block = f'## {name}\n- uid：{uid}\n- 来过：1 场\n- 第一次见：{today}\n- 最近一次：{today}\n'
                index[uid] = len(blocks)
                blocks.append(block)
            if session:
                block = set_field(block, '场次标记', session)
            if note.get('外号') and not re.search(r'^-\s*外号：\s*\S', block, flags=re.M):
                block = set_field(block, '外号', _clean(note['外号'], 12))  # 用户起的外号优先，不覆盖
            if note.get('印象'):
                block = set_field(block, '印象', _clean(note['印象'], 60))
            blocks[index[uid]] = block.rstrip('\n') + '\n\n'
        self.write(VIEWERS, head.rstrip('\n') + '\n\n' + ''.join(blocks), why)

    def save_diary(self, body, dynamic, why):
        now = self.clock()
        folder = self.dir / DIARY
        folder.mkdir(parents=True, exist_ok=True)
        name, n = f'{now:%Y-%m-%d}', 1
        while (folder / f'{name}.md').exists():
            n += 1
            name = f'{now:%Y-%m-%d}-{n}'
        text = f'# {now:%Y-%m-%d %H:%M} 下播日记\n\n{body.strip()}\n'
        if dynamic:
            text += f'\n## 动态\n{dynamic.strip()}\n'
        self.write(f'{DIARY}/{name}.md', text, why)
        return f'{DIARY}/{name}.md'

    def mark_posted(self, name, status):
        text = self.read(name)
        if '## 动态' in text:
            self.write(name, text.rstrip('\n') + f'\n\n（{_clean(status, 80)}）\n', '记录动态发布结果')
