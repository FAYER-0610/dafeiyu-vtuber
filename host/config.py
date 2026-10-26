from pathlib import Path
from urllib.parse import urlparse
import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def load_config(path=None):
    base = yaml.safe_load((ROOT / 'config.yaml').read_text(encoding='utf-8'))
    if path and Path(path).resolve() != ROOT / 'config.yaml':
        custom = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
        for section, values in custom.items():
            if isinstance(values, dict) and isinstance(base.get(section), dict):
                base[section].update(values)
            else:
                base[section] = values
    if base['server']['host'] not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('Server must bind to loopback; public binding is not supported')
    if not 1024 <= int(base['server']['port']) <= 65535:
        raise ValueError('Invalid server port')
    for section, keys in {
        'brain': ['max_tokens', 'max_text_chars', 'requests_per_minute', 'requests_per_hour',
                  'chat_replies_per_minute', 'min_gap_seconds', 'idle_seconds', 'chat_batch_seconds',
                  'queue_size', 'topic_ttl_seconds', 'dedupe_seconds', 'input_chars', 'context_turns', 'game_lines_per_minute'],
        'audio': ['playback_grace_seconds', 'max_duration_seconds', 'retention_seconds', 'max_files', 'max_bytes'],
        'game': ['snapshot_seconds', 'reconnect_seconds', 'decision_cooldown_seconds', 'topic_ttl_seconds'],
    }.items():
        if any(float(base[section][k]) <= 0 for k in keys):
            raise ValueError(f'Positive settings required in {section}')
    if base['diary']['dynamic'] not in ('auto', 'draft', 'off') or not 0 < int(base['diary']['max_tokens']) <= 3000:
        raise ValueError('diary.dynamic must be auto/draft/off; diary.max_tokens <= 3000')
    if base['brain']['max_text_chars'] > 300 or base['brain']['max_tokens'] > 500:
        raise ValueError('Safety/cost cap: max_text_chars <=300, max_tokens <=500')
    if not isinstance(base['brain'].get('viewer_memory_live', True), bool):
        raise ValueError('brain.viewer_memory_live must be true/false')
    if not 1 <= int(base['brain'].get('viewer_memory_max_tokens', 320)) <= 500:
        raise ValueError('brain.viewer_memory_max_tokens must be between 1 and 500')
    return base


def load_secrets():
    # Explicit file only: process environment cannot override or accidentally choose Key A.
    return {k: (v or '').strip() for k, v in dotenv_values(ROOT / '.env', interpolate=False).items()}


def validate_secrets(secrets, offline=False):
    game = urlparse(secrets.get('STS2_AGENT_URL') or 'http://127.0.0.1:8080')
    if game.scheme != 'http' or game.hostname not in ('127.0.0.1', 'localhost', '::1') or game.username:
        raise ValueError('STS2_AGENT_URL must be a local HTTP URL')
    if not offline:
        missing = [k for k in ('DEEPSEEK_HOST_API_KEY', 'ELEVENLABS_API_KEY', 'ELEVENLABS_VOICE_ID') if not secrets.get(k)]
        if missing:
            raise ValueError('Missing .env variable(s): ' + ', '.join(missing))
        ds = urlparse(secrets.get('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com')
        if ds.scheme != 'https' or ds.hostname != 'api.deepseek.com' or ds.username:
            raise ValueError('Only the official DeepSeek HTTPS endpoint is supported')
        if (secrets.get('DEEPSEEK_HOST_MODEL') or 'deepseek-chat') != 'deepseek-chat':
            raise ValueError('This host uses deepseek-chat only')
