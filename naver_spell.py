"""
네이버 맞춤법 검사기 클라이언트
passport key를 자동으로 갱신하며 30분 캐시합니다.
"""
import re
import time
import requests

_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Referer': 'https://search.naver.com',
}

_key_cache: dict = {'key': None, 'expires': 0.0}
MAX_CHUNK = 500   # Naver limit per request


def _get_key() -> str:
    now = time.time()
    if _key_cache['key'] and now < _key_cache['expires']:
        return _key_cache['key']

    r = requests.get(
        'https://search.naver.com/search.naver',
        params={'where': 'nexearch', 'query': '맞춤법검사기'},
        headers=_HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    keys = re.findall(r'passportKey[^a-zA-Z0-9]([a-zA-Z0-9]{20,})', r.text)
    if not keys:
        raise RuntimeError('Naver passport key를 찾을 수 없습니다.')
    _key_cache['key'] = keys[0]
    _key_cache['expires'] = now + 1800   # 30분 캐시
    return _key_cache['key']


def _call_api(text: str, key: str) -> dict:
    r = requests.get(
        'https://m.search.naver.com/p/csearch/ocontent/util/SpellerProxy',
        params={'passportKey': key, 'q': text, 'where': 'nexearch', 'color_blindness': '0'},
        headers=_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


def _parse(data: dict, original_text: str) -> dict:
    result = data.get('message', {}).get('result', {})
    errata_count = result.get('errata_count', 0)
    origin_html  = result.get('origin_html', '')
    correct_html = result.get('html', '')
    notag_html   = result.get('notag_html', original_text)

    errors      = re.findall(r"<span class='result_underline'>([^<]+)</span>", origin_html)
    # Naver uses red_text (spelling), blue_text (vocabulary), green_text (spacing)
    suggestions = re.findall(r"<em class='(?:red_text|blue_text|green_text)'>([^<]+)</em>", correct_html)

    corrections = []
    for orig, sugg in zip(errors, suggestions):
        if orig.strip() != sugg.strip():
            corrections.append({'original': orig, 'suggestion': sugg})

    lines = [f'• "{c["original"]}" → "{c["suggestion"]}"' for c in corrections]
    raw = '\n'.join(lines) if lines else '교정 제안 없음 — 맞춤법 오류가 발견되지 않았습니다.'

    return {
        'raw': raw,
        'corrections': corrections,
        'corrected_text': notag_html,
        'has_errors': errata_count > 0,
    }


def check(text: str) -> dict:
    """텍스트를 네이버 맞춤법 검사기로 교정합니다. 500자 초과 시 청크 분할."""
    key = _get_key()

    if len(text) <= MAX_CHUNK:
        data = _call_api(text, key)
        return _parse(data, text)

    # 500자씩 분할 (문장 단위로 자름)
    chunks = _split_chunks(text)
    all_corrections: list[dict] = []
    corrected_parts: list[str] = []

    for chunk in chunks:
        data = _call_api(chunk, key)
        parsed = _parse(data, chunk)
        all_corrections.extend(parsed['corrections'])
        corrected_parts.append(parsed['corrected_text'])

    lines = [f'• "{c["original"]}" → "{c["suggestion"]}"' for c in all_corrections]
    raw = '\n'.join(lines) if lines else '교정 제안 없음 — 맞춤법 오류가 발견되지 않았습니다.'

    return {
        'raw': raw,
        'corrections': all_corrections,
        'corrected_text': '\n'.join(corrected_parts),
        'has_errors': bool(all_corrections),
    }


def _split_chunks(text: str, size: int = MAX_CHUNK) -> list[str]:
    # (?<![0-9]\.) prevents splitting on numbered list items like "1. 2. 3."
    sentences = re.split(r'(?<![0-9]\.)(?<=[.!?\n])\s*', text)
    chunks, buf = [], ''
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) + 1 > size:
            if buf:
                chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + ' ' + s) if buf else s
    if buf.strip():
        chunks.append(buf.strip())
    return chunks or [text[:size]]
