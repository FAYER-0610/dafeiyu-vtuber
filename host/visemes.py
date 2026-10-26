"""Bounded, character-aligned mouth shapes; not an acoustic phoneme recognizer.

pypinyin (MIT) supplies local Mandarin finals. One dominant shape is used per
character. Original CJK alignment avoids romanized normalized-text jitter.
"""
import math
import unicodedata

MAX_VISEMES = 600
MAX_ALIGNMENT_CHARACTERS = 4096
PAUSE_SECONDS = 0.12
MIN_OPEN_SECONDS = 0.06

FINAL_GROUPS = {
    'A': {'a', 'ai', 'an', 'ang', 'ao', 'ia', 'iao', 'iang', 'ua', 'uai', 'uan', 'uang'},
    'I': {'i', 'ie', 'ian', 'in', 'ing', 'v', 've', 'van', 'vn', 'ü', 'üe', 'üan', 'ün', 'ue'},
    'U': {'u', 'ui', 'uei', 'un', 'uen', 'uo', 'ueng'},
    'E': {'e', 'ê', 'ei', 'en', 'eng', 'er'},
    'O': {'o', 'ou', 'ong', 'iong', 'iu', 'iou'},
}
FINAL_SHAPES = {final: shape for shape, finals in FINAL_GROUPS.items() for final in finals}
DIGIT_SHAPES = dict(zip('0123456789', 'IIEAIUOIAO'))


def final_viseme(final):
    """Map a toneless final (including pypinyin's expanded ü/un/ui forms)."""
    return FINAL_SHAPES.get(final.lower().replace('u:', 'ü'), 'N')


def _is_han(char):
    return 'CJK UNIFIED IDEOGRAPH' in unicodedata.name(char, '') or 'CJK COMPATIBILITY IDEOGRAPH' in unicodedata.name(char, '')


def _is_cjk(char):
    name = unicodedata.name(char, '')
    return _is_han(char) or any(script in name for script in ('HIRAGANA', 'KATAKANA', 'HANGUL'))


def _pinyin_finals(text):
    # Lazy import keeps HTTP/protocol-only tools independent of this optional
    # execution path. The package is nevertheless a required runtime dependency.
    from pypinyin import Style, lazy_pinyin
    return lazy_pinyin(text, style=Style.FINALS, strict=True, errors=lambda value: list(value))


def character_visemes(text):
    # Phrase-level conversion helps polyphones; errors callback preserves indices
    # across non-Chinese runs. Still an approximation, not guaranteed pronunciation.
    finals = _pinyin_finals(text) if any(_is_han(char) for char in text) else list(text)
    if len(finals) != len(text):
        return ['N'] * len(text)
    result = []
    for char, final in zip(text, finals):
        if char.isspace() or unicodedata.category(char)[0] in ('P', 'S', 'C'):
            shape = 'N'
        elif _is_han(char):
            shape = final_viseme(final)
        elif char.isascii() and char.isalpha():
            lower = char.lower()
            if lower in 'aeiou':
                shape = lower.upper()
            elif lower in 'bmp':
                shape = 'N'
            elif lower in 'wq':
                shape = 'U'
            elif lower in 'yj':
                shape = 'I'
            else:
                shape = 'E'
        else:
            shape = DIGIT_SHAPES.get(char, 'N')
        result.append(shape)
    return result


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def alignment_rows(alignment, duration):
    """Reject malformed/unbounded timestamps; return [] for absent alignment."""
    if not isinstance(alignment, dict) or not math.isfinite(duration) or duration <= 0:
        return []
    chars = alignment.get('characters')
    starts = alignment.get('character_start_times_seconds')
    ends = alignment.get('character_end_times_seconds')
    if not all(isinstance(value, list) for value in (chars, starts, ends)):
        return []
    if not 0 < len(chars) <= MAX_ALIGNMENT_CHARACTERS or len(chars) != len(starts) or len(chars) != len(ends):
        return []
    rows, previous_start = [], -1.0
    for char, start, end in zip(chars, starts, ends):
        if not isinstance(char, str) or len(char) != 1:
            return []
        if not all(_finite_number(t) for t in (start, end)):
            return []
        # Allow <=250ms encoder/padding differences, then clamp to MP3 duration.
        if start < previous_start or start < 0 or end < start or end > duration + 0.25:
            return []
        previous_start = start
        rows.append((char, min(float(start), duration), min(float(end), duration)))
    return rows


def select_alignment(payload, duration):
    """Prefer original CJK characters, not a romanized normalized letter stream."""
    original = alignment_rows(payload.get('alignment'), duration)
    original_valid = original and any(end > start for _, start, end in original)
    if original_valid and any(_is_cjk(char) for char, _, _ in original):
        return 'alignment', original
    normalized = alignment_rows(payload.get('normalized_alignment'), duration)
    if normalized and any(end > start for _, start, end in normalized):
        return 'normalized_alignment', normalized
    return ('alignment', original) if original_valid else (None, [])


def _smooth_short_openings(events):
    """Merge <60ms open segments, never erase an explicit neutral pause.

    Prefer holding a preceding open shape; following an N, extend the next open
    shape backwards instead. An isolated short opening between Ns is suppressed.
    """
    index = 0
    while index < len(events) - 1:
        current, following = events[index], events[index + 1]
        if index and events[index - 1]['v'] == current['v']:
            events.pop(index)
            continue
        if current['v'] == 'N' or following['t'] - current['t'] >= MIN_OPEN_SECONDS - 1e-9:
            index += 1
            continue
        if index and events[index - 1]['v'] != 'N':
            events.pop(index)
        elif following['v'] != 'N':
            current['v'] = following['v']
            events.pop(index + 1)
        else:
            current['v'] = 'N'
    merged = []
    for event in events:
        if not merged or merged[-1]['v'] != event['v']:
            merged.append(event)
    return merged


def _timeline(rows, duration):
    if not rows:
        return []
    shapes = character_visemes(''.join(row[0] for row in rows))
    candidates, previous_end = [(0.0, 'N')], 0.0
    for (_, start, end), shape in zip(rows, shapes):
        if start - previous_end > PAUSE_SECONDS:
            candidates.append((previous_end, 'N'))
        if end > start:
            candidates.append((start, shape))
        previous_end = max(previous_end, end)
    candidates.append((min(previous_end, duration), 'N'))
    # Last state wins at identical rounded times; then merge equal neighbors.
    at_time = {round(max(0.0, min(t, duration)), 3): shape for t, shape in candidates}
    result = []
    for t, shape in sorted(at_time.items()):
        if not result or shape != result[-1]['v']:
            result.append({'t': t, 'v': shape})
    result = _smooth_short_openings(result)
    if len(result) > MAX_VISEMES:
        cutoff = result[MAX_VISEMES - 1]['t']
        result = result[:MAX_VISEMES - 1]
        # Close at truncation rather than holding the last vowel to audio end.
        if result[-1]['v'] != 'N':
            result.append({'t': cutoff, 'v': 'N'})
    return result


def visemes_from_response(payload, duration):
    _, rows = select_alignment(payload, duration)
    return _timeline(rows, duration)


def synthetic_visemes(text, duration):
    """Offline visual fixture only: evenly distribute characters over test tone."""
    if not text or not math.isfinite(duration) or duration <= 0:
        return [{'t': 0.0, 'v': 'N'}]
    text = text[:MAX_ALIGNMENT_CHARACTERS]
    step = duration / len(text)
    rows = [(char, index * step, (index + 1) * step) for index, char in enumerate(text)]
    return _timeline(rows, duration)
