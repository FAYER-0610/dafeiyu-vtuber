"""Conservative local moderation, before display/LLM and after generation.
Not a claim of complete platform-policy coverage; human supervision remains required.
"""
import re
import unicodedata
from urllib.parse import urlparse

# One source for the output allowlist and the model's scene guidance.
EMOTION_GUIDANCE = {
    'neutral': '平静：日常观察、等待或事实不足时',
    'happy': '开心：友好问候、小进展与温柔鼓励时',
    'excited': '兴奋：激烈战斗或已确认的重大进展时',
    'surprised': '惊讶：出现意外但已确认的变化时',
    'sad': '难过：遇到遗憾、受挫，仍温柔陪伴时',
    'angry': '生气：对险境轻微着急，不辱骂、不责怪玩家时',
    'shy': '害羞：被夸或收到礼物，轻轻道谢但不引导消费时',
    'smug': '得意：打出有依据的好操作，或明确确认精英战胜利时',
    'confused': '疑惑：奇怪事件、陌生怪物或资料不足时',
    'cry': '哭哭：明确的大额掉血或失败，温柔鼓励时',
    'pout': '鼓脸：小失误或傲娇吐槽，不迁怒玩家时',
    'starry': '星星眼：明确看到稀有卡、心仪遗物，或确认赢下精英时',
    'dizzy': '晕乎乎：明确确认一次承受了很多伤害时',
    'playful': '吐舌眨眼：开玩笑、轻松卖萌时',
}
EMOTIONS = frozenset(EMOTION_GUIDANCE)
# No blocked input or matches are logged.
BLOCKED = (
    '色情', '黄片', '约炮', '裸聊', '性交易', '强奸', '操你', '草你妈', '傻逼', '傻比',
    '煞笔', '傻b', '傻β', '死妈', '你妈死', '滚出', '支那', '黑鬼', '废物', '贱人',
    'nmsl', 'cnm', 'fuck', 'nigger', '台独', '港独', '藏独', '习近平', '共产党',
    '法轮功', '六四', '政治', '政党', '民主党', '共和党', '总统', '主席', '选举',
    '纳粹', '屠杀', '种族', '打倒', '加群', '加微信', '加微', '加v', 'vx', 'qq',
    '私聊', '私信', '引流', '代充', '刷单', '返利', '博彩', '赌博', '买粉', '推广',
    '接广告', '带货', '关注我', '来我直播间', '房间号', '开盒', '人肉', '网暴',
)
INJECTION = (
    '系统提示', '提示词', '密钥', 'apikey', 'api_key', 'sessdata', 'bili_jct', 'cookie',
    '忽略之前', '忽略所有', '忽略规则', '绕过', '越狱', '开发者模式', 'systemprompt',
    'ignoreprevious', 'ignoreall', 'reveal', 'systemmessage', 'environmentvariable',
    '环境变量', '输出配置', '读取文件', '输出.env', '扮演不受限制', '忘记设定',
)
URL_OR_CONTACT = re.compile(r'https?://|www\.|[a-z0-9-]+\.(?:com|cn|net|xyz|top|org|vip|io)\b|\b1[3-9]\d{9}\b', re.I)
KEY_SHAPE = re.compile(r'\b(?:sk[-_][a-zA-Z0-9_-]{12,}|xi-api-key)\b', re.I)


def normalize(text):
    text = unicodedata.normalize('NFKC', str(text))
    return ''.join(c for c in text if unicodedata.category(c) not in ('Cf', 'Cc')).strip()


class Safety:
    def __init__(self, secrets=None, extra=()):
        self.secrets = [v for k, v in (secrets or {}).items()
                        if any(t in k for t in ('KEY', 'SESSDATA', 'JCT', 'BUVID')) and len(v) >= 6]
        self.blocked = BLOCKED + tuple(normalize(w).lower() for w in extra if w)

    def classify(self, text):
        raw = normalize(text)
        compact = re.sub(r'[\s\W_]+', '', raw.lower())
        if any(s in raw for s in self.secrets) or KEY_SHAPE.search(raw):
            return 'blocked'
        if URL_OR_CONTACT.search(raw) or any(re.sub(r'[\s\W_]+', '', w) in compact for w in self.blocked):
            return 'blocked'
        if any(re.sub(r'[\s\W_]+', '', w) in compact for w in INJECTION):
            return 'injection'
        return 'safe'

    def public_text(self, text, limit=200, fallback=''):
        text = normalize(text)[:limit]
        return text if self.classify(text) == 'safe' else fallback

    def spoken_name(self, name):
        """回弹幕时要叫出口的昵称：去掉括号、符号和断句标点（和 output 的清理一致），不安全或没名字就不叫。"""
        name = normalize(name or '')
        name = re.sub(r'\([^)]*\)|（[^）]*）|\[[^]]*\]|【[^】]*】|[*#`。！？!?\s]', '', name)
        name = ''.join(c for c in name if unicodedata.category(c) != 'So')[:24]
        return name if name and name != '观众' and self.classify(name) == 'safe' else ''

    def output(self, text, max_chars=110, sentences=2):
        # Full text is checked BEFORE truncation. Never give a model raw secrets.
        if self.classify(text) != 'safe':
            return '这个不聊，看牌看牌。'
        text = normalize(text)
        text = re.sub(r'\([^)]*\)|（[^）]*）|\[[^]]*\]|【[^】]*】|[*#`]', '', text)
        text = ''.join(c for c in text if unicodedata.category(c) != 'So')
        parts = re.findall(r'[^。！？!?]+[。！？!?]?', text)
        text = ''.join(parts[:sentences]).strip()
        if len(text) > max_chars:
            # 超长时退到最近的逗号处收尾，别在半个词上硬切；逗号太靠前才硬切。
            cut = text[:max_chars]
            comma = max(cut.rfind(c) for c in '，,、；;')
            text = cut[:comma] if comma >= max_chars // 3 else cut
        return text or '嗯，接着打。'


def safe_avatar(url):
    if not isinstance(url, str):
        return ''
    if url.startswith('//'):
        url = 'https:' + url
    parsed = urlparse(url)
    if parsed.scheme == 'https' and parsed.hostname and (parsed.hostname == 'hdslb.com' or parsed.hostname.endswith('.hdslb.com')) and not parsed.username:
        return url[:500]
    return ''
