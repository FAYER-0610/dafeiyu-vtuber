import asyncio
import base64
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from aiohttp.test_utils import TestClient, TestServer
from host.config import load_config
from host.providers import AudioStore, ProviderError, TTS
from host.visemes import (MAX_VISEMES, alignment_rows, character_visemes, final_viseme,
                          select_alignment, synthetic_visemes, visemes_from_response)
from host.web import Hub, create_app

ROOT = Path(__file__).resolve().parents[1]


def alignment(text, starts=None, ends=None):
    return {'characters': list(text),
            'character_start_times_seconds': starts if starts is not None else [i * .1 for i in range(len(text))],
            'character_end_times_seconds': ends if ends is not None else [(i + 1) * .1 for i in range(len(text))]}


class VisemeTests(unittest.TestCase):
    def test_required_mandarin_final_groups(self):
        groups = {'A': ['a', 'ia', 'ua', 'ai', 'ao', 'an', 'ang', 'iang', 'uan'],
                  'O': ['o', 'ou', 'ong', 'iong', 'iou'],
                  'E': ['e', 'ei', 'en', 'eng', 'er'],
                  'I': ['i', 'in', 'ing', 'ü', 'v', 'ie', 'ian', 'üe', 'van'],
                  'U': ['u', 'un', 'uo', 'uen', 'uei']}
        for shape, finals in groups.items():
            for final in finals:
                self.assertEqual(final_viseme(final), shape, final)
        self.assertEqual(final_viseme('u:'), 'I')
        self.assertEqual(final_viseme('unknown'), 'N')

    def test_phrase_mapping_and_index_preservation_with_stub(self):
        # This tests our adapter independently of the externally installed library.
        with patch('host.visemes._pinyin_finals', return_value=['ia', 'ian', 'v', ' ', 'a', '!']) as convert:
            self.assertEqual(character_visemes('家天女 a!'), ['A', 'I', 'I', 'N', 'A', 'N'])
            convert.assert_called_once_with('家天女 a!')

    @unittest.skipUnless(importlib.util.find_spec('pypinyin'), 'pypinyin runtime dependency not installed')
    def test_real_pypinyin_phrase_conversion(self):
        self.assertEqual(character_visemes('家天女乌国欧恩。'), ['A', 'I', 'I', 'U', 'U', 'O', 'E', 'N'])
        self.assertEqual(len(character_visemes('小鲸鱼 HP28!')), len('小鲸鱼 HP28!'))

    def test_english_punctuation_and_digits(self):
        self.assertEqual(character_visemes('aeiou bmp! '), list('AEIOUNNNNNN'))
        self.assertEqual(character_visemes('28'), ['E', 'A'])

    def test_adjacent_merge_pause_and_final_neutral(self):
        result = visemes_from_response({'alignment': alignment('aaei', [0, .1, .5, .6], [.1, .2, .6, .7])}, 1)
        self.assertEqual(result, [{'t': 0.0, 'v': 'A'}, {'t': .2, 'v': 'N'}, {'t': .5, 'v': 'E'},
                                  {'t': .6, 'v': 'I'}, {'t': .7, 'v': 'N'}])

    def test_leading_silence_punctuation_and_rounding(self):
        result = visemes_from_response({'alignment': alignment('a,e', [.1504, .2544, .3014], [.2544, .3014, .4054])}, 1)
        self.assertEqual(result, [{'t': 0.0, 'v': 'N'}, {'t': .15, 'v': 'A'}, {'t': .254, 'v': 'N'},
                                  {'t': .301, 'v': 'E'}, {'t': .405, 'v': 'N'}])

    def test_normalized_preferred_and_same_response_fallback(self):
        payload = {'alignment': alignment('a'), 'normalized_alignment': alignment('o')}
        self.assertEqual(select_alignment(payload, 1)[0], 'normalized_alignment')
        self.assertEqual(visemes_from_response(payload, 1)[0]['v'], 'O')
        payload['normalized_alignment'] = alignment('o', [float('nan')], [.1])
        self.assertEqual(select_alignment(payload, 1)[0], 'alignment')
        self.assertEqual(visemes_from_response(payload, 1)[0]['v'], 'A')

    def test_reconstructed_cjk_normalization_regression(self):
        # Reconstructed from observed lengths (12 original / 37 normalized), NOT
        # an exact captured response: the first real probe did not save arrays.
        text = '小鲸鱼，今天加油，28。'
        romanized = 'xiao jing yu jin tian jia you, er ba.'
        self.assertEqual((len(text), len(romanized)), (12, 37))
        payload = {'alignment': alignment(text, [.023 + i * .15 for i in range(12)], [.163 + i * .15 for i in range(12)]),
                   'normalized_alignment': alignment(romanized, [.023 + i * .035 for i in range(37)], [.058 + i * .035 for i in range(37)])}
        self.assertEqual(select_alignment(payload, 2.273)[0], 'alignment')
        with patch('host.visemes._pinyin_finals', return_value=['iao', 'ing', 'v', ',', 'in', 'ian', 'ia', 'iou', ',', '2', '8', '.']):
            result = visemes_from_response(payload, 2.273)
        self.assertEqual(next(item['v'] for item in result if item['v'] != 'N'), 'A')
        self.assertLess(len(result), 20)
        self.assertTrue(all(a['v'] == 'N' or b['t'] - a['t'] >= .06 - 1e-9 for a, b in zip(result, result[1:])))
        self.assertEqual(result[-1]['v'], 'N')
        # Also retain the next user-run probe's exact arrays, without audio/secrets.
        captured = json.loads((ROOT / 'tests' / 'fixtures' / 'elevenlabs_chinese_alignment.json').read_text(encoding='utf-8'))
        self.assertFalse(captured['is_reconstructed'])
        self.assertEqual(select_alignment(captured, captured['duration_s'])[0], 'alignment')
        with patch('host.visemes._pinyin_finals', return_value=['iao', 'ing', 'v', ',', 'in', 'ian', 'ia', 'iou', ',', '2', '8', '.']):
            self.assertEqual(visemes_from_response(captured, captured['duration_s']), captured['expected_visemes'])

    def test_short_segments_merge_but_neutral_pause_survives(self):
        payload = {'alignment': alignment('aei,o', [0, .035, .07, .105, .12], [.035, .07, .105, .12, .22])}
        self.assertEqual(visemes_from_response(payload, 1), [{'t': 0.0, 'v': 'E'}, {'t': .105, 'v': 'N'},
                                                           {'t': .12, 'v': 'O'}, {'t': .22, 'v': 'N'}])
        isolated = {'alignment': alignment('a', [.2], [.23])}
        self.assertEqual(visemes_from_response(isolated, 1), [{'t': 0.0, 'v': 'N'}])

    def test_empty_alignment(self):
        for payload in ({}, {'alignment': None}, {'alignment': alignment('')}, {'normalized_alignment': {}},
                        {'alignment': alignment('a', [0], [0])}):
            self.assertEqual(visemes_from_response(payload, 1), [])

    def test_invalid_and_excessive_alignment_is_rejected(self):
        invalid = [alignment('a', [], [.1]), alignment('a', [-.1], [.1]),
                   alignment('a', [True], [.1]), alignment('a', [0], [float('inf')]),
                   alignment('ae', [.2, .1], [.3, .2]), alignment('a', [.2], [.1]),
                   alignment('a', [0], [2]), alignment('a', [0], [10 ** 4000]), alignment('a' * 4097)]
        for value in invalid:
            self.assertEqual(alignment_rows(value, 1), [])

    def test_length_cap_closes_at_truncation(self):
        text = 'ae' * 350
        value = alignment(text, [i * .07 for i in range(len(text))], [(i + 1) * .07 for i in range(len(text))])
        result = visemes_from_response({'alignment': value}, 50)
        self.assertLessEqual(len(result), MAX_VISEMES)
        self.assertEqual(result[-1]['v'], 'N')
        self.assertLess(result[-1]['t'], 49)
        self.assertTrue(all(a['t'] < b['t'] and a['v'] != b['v'] for a, b in zip(result, result[1:])))

    def test_rounding_collision_keeps_one_state(self):
        result = visemes_from_response({'alignment': alignment('ae', [0, .0002], [.0002, .1])}, 1)
        self.assertEqual(result, [{'t': 0.0, 'v': 'E'}, {'t': .1, 'v': 'N'}])

    def test_offline_synthetic_timeline(self):
        self.assertEqual(synthetic_visemes('ai!', 1), [{'t': 0.0, 'v': 'A'}, {'t': .333, 'v': 'I'}, {'t': .667, 'v': 'N'}])
        self.assertEqual(synthetic_visemes('', 1), [{'t': 0.0, 'v': 'N'}])


class FakeResponse:
    def __init__(self, body, status=200):
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.status = status
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def iter_chunked(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]


class FakeSession:
    def __init__(self, response):
        self.response, self.calls = response, []

    def post(self, endpoint, **kwargs):
        self.calls.append((endpoint, kwargs))
        return self.response


class TTSVisemeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT / 'runtime')
        self.addCleanup(self.folder.cleanup)
        self.store = AudioStore(self.folder.name, load_config()['audio'])
        self.secrets = {'ELEVENLABS_VOICE_ID': 'fakeVoice', 'ELEVENLABS_API_KEY': 'fake-not-a-real-key'}

    async def test_timestamp_endpoint_audio_and_visemes(self):
        data = {'audio_base64': base64.b64encode(b'mock-mp3').decode(), 'alignment': alignment('a'), 'normalized_alignment': alignment('e')}
        session = FakeSession(FakeResponse(data))
        with patch('host.providers.MP3', return_value=SimpleNamespace(info=SimpleNamespace(length=1.0))):
            result = await TTS(session, self.secrets, self.store).synthesize('a')
        endpoint, kwargs = session.calls[0]
        self.assertTrue(endpoint.endswith('/fakeVoice/with-timestamps'))
        self.assertEqual(kwargs['params']['output_format'], 'mp3_44100_128')
        self.assertEqual(kwargs['json']['model_id'], 'eleven_v4_turbo')
        self.assertEqual(kwargs['json']['language_code'], 'zh')
        self.assertEqual(kwargs['headers']['Accept'], 'application/json')
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual((self.store.directory / Path(result['audio_url']).name).read_bytes(), b'mock-mp3')
        self.assertEqual(result['visemes'][0]['v'], 'E')

    async def test_timestamp_http_failure_has_no_fallback(self):
        session = FakeSession(FakeResponse({'private': 'never echo body'}, status=403))
        with self.assertRaisesRegex(ProviderError, '^ElevenLabs HTTP 403$'):
            await TTS(session, self.secrets, self.store).synthesize('a')
        self.assertEqual(len(session.calls), 1)
        self.assertFalse(list(self.store.directory.iterdir()))

    async def test_invalid_base64_has_no_fallback(self):
        session = FakeSession(FakeResponse({'audio_base64': '***not-base64***'}))
        with self.assertRaisesRegex(ProviderError, '^ElevenLabs invalid timestamp response$'):
            await TTS(session, self.secrets, self.store).synthesize('a')
        self.assertEqual(len(session.calls), 1)

    async def test_json_response_size_bound(self):
        session = FakeSession(FakeResponse(b'x' * 6_000_001))
        with self.assertRaisesRegex(ProviderError, 'response too large'):
            await TTS(session, self.secrets, self.store).synthesize('a')
        self.assertEqual(len(session.calls), 1)

    async def test_audio_without_alignment_has_empty_optional_timeline(self):
        session = FakeSession(FakeResponse({'audio_base64': base64.b64encode(b'mock-mp3').decode()}))
        with patch('host.providers.MP3', return_value=SimpleNamespace(info=SimpleNamespace(length=1.0))):
            result = await TTS(session, self.secrets, self.store).synthesize('a')
        self.assertEqual(result['visemes'], [])

    async def test_offline_tts_never_calls_provider(self):
        session = FakeSession(FakeResponse({}, 500))
        with patch('host.visemes._pinyin_finals', return_value=['ia', 'i']):
            result = await TTS(session, {}, self.store, offline=True).synthesize('家衣')
        self.assertEqual(session.calls, [])
        self.assertTrue(result['audio_url'].endswith('.wav'))
        self.assertEqual(result['visemes'], [{'t': 0.0, 'v': 'A'}, {'t': .5, 'v': 'I'}, {'t': 1.0, 'v': 'N'}])

    async def test_missing_local_dependency_fails_before_paid_call(self):
        session = FakeSession(FakeResponse({}, 500))
        with patch('host.visemes._pinyin_finals', side_effect=ImportError):
            with self.assertRaisesRegex(ProviderError, 'dependency unavailable'):
                await TTS(session, self.secrets, self.store).synthesize('鲸')
        self.assertEqual(session.calls, [])

    async def test_avatar_receives_history_broadcasts_and_visemes(self):
        hub = Hub('test', 'offline', load_config()['audio'])
        hub.history = [{'id': 'history-item', 'text': 'safe fixture'}]
        async with TestClient(TestServer(create_app(hub, self.store))) as client:
            ws = await client.ws_connect('/ws')
            hello = await ws.receive_json()
            await ws.receive_json()  # initial status
            history = await ws.receive_json()
            self.assertEqual(history['items'], hub.history)
            await ws.send_json({'type': 'hello', 'role': 'avatar', 'ready': True})
            self.assertEqual((await ws.receive_json())['type'], 'player')
            self.assertEqual((await ws.receive_json())['type'], 'status')
            await hub.broadcast('danmaku', item={'id': 'new-item'})
            self.assertEqual((await ws.receive_json())['type'], 'danmaku')
            await hub.status_update(game={'hp': 10, 'max_hp': 80})
            self.assertEqual((await ws.receive_json())['game']['hp'], 10)
            speech = {'id': 'with-mouth', 'text': 'a', 'emotion': 'happy', 'duration_s': 1,
                      'visemes': [{'t': 0.0, 'v': 'A'}, {'t': 1.0, 'v': 'N'}]}
            task = asyncio.create_task(hub.play(speech))
            while True:
                message = await asyncio.wait_for(ws.receive_json(), 2)
                if message['type'] == 'speech':
                    break
            self.assertEqual(message['visemes'], speech['visemes'])
            self.assertEqual(message['player_id'], hello['client_id'])
            await ws.send_json({'type': 'speech_done', 'id': speech['id'], 'status': 'ended'})
            while (message := await asyncio.wait_for(ws.receive_json(), 2))['type'] != 'idle':
                pass
            self.assertEqual(message['last_speech_id'], speech['id'])
            self.assertEqual(await task, 'ended')
            await ws.close()


if __name__ == '__main__':
    unittest.main()
