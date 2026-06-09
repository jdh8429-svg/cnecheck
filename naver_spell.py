"""
네이버 맞춤법 검사기 클라이언트
passport key를 자동으로 갱신하며 30분 캐시합니다.
"""
import re
import time
import html as html_lib
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


# ── 교정 필터 ───────────────────────────────────────────────

def _char_set(s: str) -> set:
    """한글·영문만 추출한 글자 집합 (공백·기호 제외)."""
    return set(re.sub(r'[^가-힣A-Za-z]', '', s))


def _overlap_ratio(a: str, b: str) -> float:
    """두 문자열의 Jaccard 유사도 (글자 집합 기준)."""
    ca, cb = _char_set(a), _char_set(b)
    if not ca or not cb:
        return 1.0
    return len(ca & cb) / len(ca | cb)


def _should_skip(orig: str, sugg: str) -> bool:
    """
    True를 반환하면 해당 교정 항목을 출력에서 제외합니다.

    적용 규칙:
    1. HTML 엔티티(&quot; 등)가 제안에 포함된 경우 제외
    2. 영문+한글 혼용 원문 → 고유명사(SFA반도체 등) 보호
    3. '앤' 포함 원문 → 브랜드명 표기(블루원골프앤리조트 등) 보호
    4. 글자 유사도 0.4 미만 → 정렬 오류(misalignment)로 판단, 제외
    """
    # 1. HTML 엔티티 필터
    if re.search(r'&[a-zA-Z#][^;]{0,8};', sugg):
        return True

    # 2. 영문+한글 혼용 → 고유명사 추정 (예: SFA반도체, QR코드)
    if re.search(r'[A-Za-z]', orig) and re.search(r'[가-힣]', orig):
        return True

    # 3. '앤' 포함 → 브랜드명 표기 보호 (예: 에프앤에이치, 골프앤리조트)
    if '앤' in orig:
        return True

    # 4. 글자 유사도 < 0.4 → 정렬 오류 또는 전혀 다른 단어 제안
    if _overlap_ratio(orig, sugg) < 0.4:
        return True

    # 5. 띄어쓰기만 다르고 공백이 2개 이상 추가된 경우 → 회사명·기관명 과분할로 판단
    #    (예: 웅진보안시스템→웅진 보안 시스템 은 2개 추가 → 차단)
    #    (예: 지속가능한→지속 가능한 은 1개 추가 → 허용)
    orig_kor = re.sub(r'[^가-힣]', '', orig)
    sugg_kor = re.sub(r'[^가-힣]', '', sugg)
    if orig_kor == sugg_kor and (sugg.count(' ') - orig.count(' ')) >= 2:
        return True

    return False


# ── 파싱 ────────────────────────────────────────────────────

def _parse(data: dict, original_text: str) -> dict:
    result = data.get('message', {}).get('result', {})
    errata_count = result.get('errata_count', 0)
    origin_html  = result.get('origin_html', '')
    correct_html = result.get('html', '')
    notag_html   = html_lib.unescape(result.get('notag_html', original_text))

    errors      = re.findall(r"<span class='result_underline'>([^<]+)</span>", origin_html)
    suggestions = re.findall(r"<em class='(?:red_text|blue_text|green_text)'>([^<]+)</em>", correct_html)

    corrections = []
    for orig, sugg in zip(errors, suggestions):
        orig = html_lib.unescape(orig).strip()
        sugg = html_lib.unescape(sugg).strip()

        if orig == sugg:
            continue

        if _should_skip(orig, sugg):
            continue

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
