"""
오프라인 한국어 맞춤법 교정 엔진 — 공문서·보도자료 특화
국립국어원 맞춤법 규정 + 공공언어 바른 표현 기준
"""
import re
from dataclasses import dataclass

@dataclass
class Correction:
    original: str
    suggestion: str
    rule: str
    start: int
    end: int


# ── 규칙 정의 ─────────────────────────────────────────────────
# (pattern, replacement, rule_description)
# replacement가 None이면 패턴 검출만 (수동 표시)

RULES: list[tuple[str, str | None, str]] = [

    # ─ 됐다/됬다 ─
    (r'됬', '됐', '됐다 계열: "됬"은 잘못된 표기, "됐"으로 써야 합니다.'),
    (r'됬습니다', '됐습니다', '됐습니다: "됬"은 잘못된 표기입니다.'),

    # ─ 않/안 ─
    (r'안됩니다', '안 됩니다', '"안됩니다"는 "안 됩니다"로 띄어 씁니다.'),
    (r'안되', '안 되', '"안되"는 "안 되"로 띄어 씁니다. (단, "안되다"는 붙여 씀)'),

    # ─ 어떻하다 / 어떡해 ─
    (r'어떻해', '어떡해', '"어떻해"는 "어떡해"로 씁니다.'),
    (r'어떻하', '어떡하', '"어떻하"는 "어떡하"로 씁니다.'),

    # ─ 작성되었슴니다 계열 ─
    (r'습니다\s*([.!?])', r'습니다\1', ''),   # 정상
    (r'슴니다', '습니다', '"슴니다"는 "습니다"로 써야 합니다.'),
    (r'읍니다', '습니다', '"읍니다"는 "습니다"로 써야 합니다.'),
    (r'겠읍니다', '겠습니다', '"겠읍니다"는 "겠습니다"로 써야 합니다.'),

    # ─ 열심이/열심히 ─
    (r'열심이\s+(?!하)', '열심히 ', '"열심이"는 부사이므로 "열심히"로 써야 합니다.'),

    # ─ -로서/-로써 ─
    (r'(\S+)(으)로써\s+(된|이뤄|구성|이루)', r'\1\2로서 \4', '자격·신분을 나타낼 때는 "-로서"를 씁니다.'),

    # ─ 로서/로써 구분 (도구/수단) ─
    (r'(\S+)(으)로서\s+(삼아|사용|활용|쓰)', r'\1\2로써 \4', '수단·방법을 나타낼 때는 "-로써"를 씁니다.'),

    # ─ 반드시/반듯이 ─
    (r'반듯이\s+(?!앉|서|눕|세)', '반드시 ', '꼭·틀림없이의 뜻은 "반드시"입니다.'),

    # ─ 왠/웬 ─
    (r'왠만하면', '웬만하면', '"왠만하면"은 "웬만하면"으로 씁니다.'),
    (r'웬지', '왠지', '"웬지"는 "왠지"로 씁니다.'),

    # ─ 이따가/있다가 ─
    (r'있다가(?!\s*먹|\s*마|\s*자|\s*놀|\s*기다)', '이따가', '시간적 의미의 "있다가"는 "이따가"로 써야 합니다.'),

    # ─ 뵈/봬 ─
    (r'봬요', '뵈어요', '"봬요" → "뵈어요" 또는 "뵙겠습니다"가 올바릅니다.'),

    # ─ 되/돼 ─
    (r'되어야\s*겠', '돼야겠', '"되어야겠"은 "돼야겠"으로 줄여 씁니다.'),
    (r'(?<![가-힣])되서', '돼서', '"되서"는 "돼서"로 써야 합니다.'),

    # ─ 틀리다/다르다 ─
    (r'틀린\s+(?:것|부분|점|내용)', '다른 ', '차이를 나타낼 때는 "틀리다" 대신 "다르다"를 씁니다.'),

    # ─ 및/그리고/또는 혼용 ─
    (r'및\s+또는', '또는', '"및"과 "또는"을 같이 쓰면 중복입니다.'),

    # ─ 공문서 띄어쓰기 ─
    (r'각각의\s+(?:다음|아래|상기)', '다음의 각', '공문서 관행 표현으로 "다음의 각"이 자연스럽습니다.'),

    # ─ 외래어 한글 표기 오류 (국립국어원 기준) ─
    (r'컨텐츠', '콘텐츠', '국립국어원: "컨텐츠" → "콘텐츠"'),
    (r'컨텐트', '콘텐츠', '국립국어원: "컨텐트" → "콘텐츠"'),
    (r'인터넷\s*홈페이지', '인터넷 누리집', '공공언어: "홈페이지" → "누리집"'),
    (r'리더쉽', '리더십', '국립국어원: "리더쉽" → "리더십"'),
    (r'워크샵', '워크숍', '국립국어원: "워크샵" → "워크숍"'),
    (r'심포지움', '심포지엄', '국립국어원: "심포지움" → "심포지엄"'),
    (r'브리핑', '브리핑', ''),   # 정상 표기
    (r'레포트', '리포트', '국립국어원: "레포트" → "리포트"'),
    (r'프리젠테이션', '프레젠테이션', '국립국어원: "프리젠테이션" → "프레젠테이션"'),
    (r'미팅', '회의', '공공언어 순화어: "미팅" → "회의"를 권장합니다.'),
    (r'메뉴얼', '매뉴얼', '국립국어원: "메뉴얼" → "매뉴얼"'),
    (r'마케팅', '홍보·마케팅', ''),   # 정상

    # ─ 공문서 어미 ─
    (r'하여야\s+합니다', '하여야 합니다', ''),   # 정상
    (r'하면\s+안됩니다', '하면 안 됩니다', '"안됩니다"는 "안 됩니다"로 띄어 씁니다.'),
    (r'할수\s+있', '할 수 있', '"할수"는 "할 수"로 띄어 씁니다.'),
    (r'할수\s+없', '할 수 없', '"할수"는 "할 수"로 띄어 씁니다.'),
    (r'수\s+있도록', '수 있도록', ''),   # 정상
    (r'바\s+랍니다', '바랍니다', '"바 랍니다"는 "바랍니다"로 붙여 씁니다.'),

    # ─ 높임말 오류 ─
    (r'말씀\s*드리겠습니다', '말씀드리겠습니다', '"말씀 드리겠습니다"는 "말씀드리겠습니다"로 붙여 씁니다.'),

    # ─ 흔한 오류 ─
    (r'이\s*후\s*에도', '이후에도', '"이 후에도"는 "이후에도"로 붙여 씁니다.'),
    (r'앞\s*으로도', '앞으로도', '"앞 으로도"는 "앞으로도"로 붙여 씁니다.'),
    (r'더\s*불어', '더불어', '"더 불어"는 "더불어"로 붙여 씁니다.'),

    # ─ 접속사 띄어쓰기 ─
    (r'그\s*러나', '그러나', '"그 러나"는 "그러나"로 붙여 씁니다.'),
    (r'따\s*라서', '따라서', '"따 라서"는 "따라서"로 붙여 씁니다.'),

    # ─ 존칭 과잉 ─
    (r'고객님께서는\s+반드시', '고객님은 반드시', '"께서는"과 "반드시" 조합에서 주어 격조사 확인 필요.'),
]

# 빈 rule_description은 내부 처리 제외
RULES = [(p, r, d) for p, r, d in RULES if d]


def check(text: str) -> dict:
    """텍스트에서 맞춤법 오류를 검출하여 반환."""
    corrections = []
    used_spans: list[tuple[int, int]] = []

    for pattern, replacement, desc in RULES:
        for m in re.finditer(pattern, text):
            start, end = m.start(), m.end()
            # 이미 교정된 위치와 겹치면 건너뜀
            if any(s <= start < e or s < end <= e for s, e in used_spans):
                continue
            original = m.group(0)
            if replacement:
                suggestion = re.sub(pattern, replacement, original)
            else:
                suggestion = original

            if original != suggestion:
                corrections.append(Correction(
                    original=original,
                    suggestion=suggestion,
                    rule=desc,
                    start=start,
                    end=end,
                ))
                used_spans.append((start, end))

    corrections.sort(key=lambda c: c.start)

    # 교정이 적용된 전체 텍스트 생성
    corrected = text
    offset = 0
    for c in corrections:
        s, e = c.start + offset, c.end + offset
        corrected = corrected[:s] + c.suggestion + corrected[e:]
        offset += len(c.suggestion) - (e - s)

    lines = []
    for c in corrections:
        lines.append(f'• "{c.original}" → "{c.suggestion}"\n  근거: {c.rule}')

    raw = '\n\n'.join(lines) if lines else '교정 제안 없음 — 맞춤법 오류가 발견되지 않았습니다.'

    return {
        'raw': raw,
        'corrections': [
            {'original': c.original, 'suggestion': c.suggestion, 'rule': c.rule}
            for c in corrections
        ],
        'corrected_text': corrected,
        'has_errors': bool(corrections),
    }


if __name__ == '__main__':
    sample = '이 보고서는 우리 팀의 노력으로 작성됬습니다. 앞으로도 열심이 하겠읍니다. 컨텐츠를 활용한 홍보 미팅도 잡겠슴니다.'
    result = check(sample)
    print(result['raw'])
    print()
    print('교정문:', result['corrected_text'])
