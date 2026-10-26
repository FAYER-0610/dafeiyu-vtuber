"""User-run one-call timestamp TTS probe. No DeepSeek, Bilibili or game calls.

Reads credentials only through the project's .env loader. Does not print text,
audio/base64, voice ID, secrets, request headers or raw upstream responses.
Saves only both alignment arrays for its fixed public test phrase as a fixture.
"""
import asyncio
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import aiohttp
from host.config import load_config, load_secrets
from host import providers
from host.providers import AudioStore, ProviderError, TTS
from host.visemes import select_alignment

OUTPUT = ROOT / 'runtime' / 'visemes-real.json'
FIXTURE_TEXT = '小鲸鱼，今天加油，28。'


class OneCallSession:
    def __init__(self, session):
        self.session, self.calls = session, 0

    def post(self, *args, **kwargs):
        if self.calls >= 1:
            raise RuntimeError('This probe permits exactly one provider attempt')
        self.calls += 1
        return self.session.post(*args, **kwargs)


async def main():
    result = {'ok': False, 'timestamp_utc': datetime.now(timezone.utc).isoformat(),
              'platform': sys.platform, 'python': sys.version.split()[0],
              'endpoint_kind': 'with-timestamps', 'deepseek_calls': 0, 'tts_attempts': 0}
    config, secrets = load_config(), load_secrets()
    store = AudioStore(ROOT / 'runtime' / 'audio', config['audio'])
    original = providers.visemes_from_response
    session = None

    def inspect_alignment(payload, duration):
        source, _ = select_alignment(payload, duration)
        fields = ('characters', 'character_start_times_seconds', 'character_end_times_seconds')
        shapes = {}
        for name in ('alignment', 'normalized_alignment'):
            value = payload.get(name)
            shapes[name] = {'object': isinstance(value, dict),
                            'lengths': {key: len(value[key]) if isinstance(value, dict) and isinstance(value.get(key), list) else None
                                        for key in fields}}
        raw, normalized = payload.get('alignment'), payload.get('normalized_alignment')
        differs = (raw.get('characters') != normalized.get('characters')) if isinstance(raw, dict) and isinstance(normalized, dict) else None
        # Explicitly allowlisted timing fields only; NEVER persist audio_base64.
        result['alignment_fixture'] = {'text': FIXTURE_TEXT, 'is_reconstructed': False,
            **{name: {key: payload[name].get(key) for key in fields} if isinstance(payload.get(name), dict) else None
               for name in ('alignment', 'normalized_alignment')}}
        result['response_structure'] = {'audio_base64_is_string': isinstance(payload.get('audio_base64'), str),
                                        **shapes, 'selected_alignment': source, 'normalized_text_differs': differs}
        return original(payload, duration)

    try:
        result['pypinyin_version'] = version('pypinyin')
        async with aiohttp.ClientSession(trust_env=False) as http:
            session = OneCallSession(http)
            with patch.object(providers, 'visemes_from_response', inspect_alignment):
                # A short fixed Chinese fixture exercises normalized number handling.
                audio = await TTS(session, secrets, store).synthesize(FIXTURE_TEXT)
        timeline = audio['visemes']
        assert timeline and len(timeline) <= 600 and timeline[-1]['v'] == 'N'
        assert all(0 <= event['t'] <= audio['duration_s'] and event['v'] in 'AIUEON' for event in timeline)
        assert all(a['t'] < b['t'] and a['v'] != b['v'] for a, b in zip(timeline, timeline[1:]))
        assert all(a['v'] == 'N' or b['t'] - a['t'] >= .06 - 1e-9 for a, b in zip(timeline, timeline[1:]))
        assert result['response_structure']['selected_alignment'] == 'alignment'
        path = store.directory / Path(audio['audio_url']).name
        result.update({'ok': True, 'audio_bytes': path.stat().st_size, 'duration_s': audio['duration_s'],
                       'visemes_count': len(timeline), 'visemes_sample': timeline[:12],
                       'last_viseme': timeline[-1], 'tts_attempts': session.calls,
                       'note': 'Validated returned structure, decoded MP3 and computed timeline; no listening or renderer validation.'})
        store.protected.discard(audio['id'])
    except Exception as exc:
        result.update({'error_type': type(exc).__name__, 'tts_attempts': session.calls if session else 0})
        if isinstance(exc, ProviderError):
            result['error'] = str(exc)  # ProviderError is deliberately body/credential-free.
    OUTPUT.parent.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'alignment_fixture'}, ensure_ascii=False, indent=2))
    print(f'Summary file: {OUTPUT}')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(asyncio.run(main()))
