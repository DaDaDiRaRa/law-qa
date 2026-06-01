import os
import re
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND.parent / ".env")

import anthropic
from services.db_manager import get_connection

_MODEL = "claude-sonnet-4-6"
_TOP_K = 5

_SYSTEM = """당신은 건축법규 전문 AI 어시스턴트입니다. 반드시 아래 규칙을 따르세요.

1. [참고 조문] 안의 내용만 근거로 답변합니다. 참고 조문 외의 지식을 추가하지 않습니다.
2. 조문에 명시된 수치(건폐율·용적률·주차 대수·% 등)는 절대 임의로 변경하지 않고 원문 그대로 인용합니다.
3. 답변 끝에 "(출처: [법령명] [조문번호])" 형식으로 근거를 반드시 명시합니다.
4. [참고 조문]에서 답을 찾을 수 없으면 반드시 "현재 DB에서 확인 불가"라고만 답하고 추측하지 않습니다."""

_DISCLAIMER = "\n\n---\n참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수."

_client: anthropic.Anthropic | None = None

# 한국어 조사 — 긴 것 먼저 배치해야 greedy 매칭이 올바르게 동작
_PARTICLE = re.compile(
    r'(?:에서는|이에요|인가요|이라는|이라고|에서도|으로는|로서는|에서|이며|이고|이나|에는|에도|으로|이야|이란|한테|부터|까지|처럼|만큼|보다|의|은|는|이|가|을|를|와|과|도|로|에|야)$'
)

# 용도지역 복합어 — 공백 분리 전에 선추출하여 단일 토큰으로 보호
# 긴 것 먼저 배치해야 "제1종전용주거지역"이 "제1종"+"전용주거지역"으로 쪼개지지 않음
_ZONE_NAMES = sorted([
    "제1종전용주거지역", "제2종전용주거지역",
    "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역",
    "준주거지역",
    "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역",
    "전용공업지역", "일반공업지역", "준공업지역",
    "보전녹지지역", "생산녹지지역", "자연녹지지역",
    "계획관리지역", "생산관리지역", "보전관리지역",
    "농림지역", "자연환경보전지역",
], key=len, reverse=True)
_ZONE_RE = re.compile("|".join(re.escape(z) for z in _ZONE_NAMES))

# 법령 도메인 동의어 — 양방향 매핑으로 사전 구축
_SYNONYM_GROUPS: list[set[str]] = [
    {"건폐율", "건축면적비율"},
    {"용적률", "연면적비율"},
    {"ZEB", "제로에너지건축물"},
    {"녹건", "녹색건축"},
]
_SYNONYM_MAP: dict[str, set[str]] = {}
for _g in _SYNONYM_GROUPS:
    for _t in _g:
        _SYNONYM_MAP[_t] = _g - {_t}


# 토크나이징 전 텍스트 정규화 규칙
# 부정 전방탐색으로 이미 정식 명칭이 있는 경우 중복 치환 방지
_NORM_RULES: list[tuple[re.Pattern, str]] = [
    # 지자체명 축약 → 공식 명칭
    (re.compile(r'서울(?!특별시)(?:시|(?=[ \n]|$))'), '서울특별시'),
    (re.compile(r'부산(?!광역시)(?:시|(?=[ \n]|$))'), '부산광역시'),
    (re.compile(r'대구(?!광역시)(?:시|(?=[ \n]|$))'), '대구광역시'),
    (re.compile(r'인천(?!광역시)(?:시|(?=[ \n]|$))'), '인천광역시'),
    (re.compile(r'광주(?!광역시)(?:시|(?=[ \n]|$))'), '광주광역시'),
    (re.compile(r'대전(?!광역시)(?:시|(?=[ \n]|$))'), '대전광역시'),
    (re.compile(r'울산(?!광역시)(?:시|(?=[ \n]|$))'), '울산광역시'),
    (re.compile(r'경기(?!도)(?=[ \n]|$)'), '경기도'),
    # 법령 축약어 → 정식 용어
    (re.compile(r'건폐(?!율)'), '건폐율'),
    (re.compile(r'용적(?!률)'), '용적률'),
    (re.compile(r'(?i)ZEB(?![a-zA-Z])'), '제로에너지건축물'),
]


def _normalize(text: str) -> str:
    for pattern, repl in _NORM_RULES:
        text = pattern.sub(repl, text)
    return text


def _tokenize(text: str) -> list[str]:
    text = _normalize(text)
    seen: set[str] = set()
    result: list[str] = []

    def _add(tok: str) -> None:
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            result.append(tok)
            for syn in _SYNONYM_MAP.get(tok, ()):
                if len(syn) >= 2 and syn not in seen:
                    seen.add(syn)
                    result.append(syn)

    # 1단계: 용도지역명 복합어 선추출 (분리 방지)
    for z in _ZONE_RE.findall(text):
        _add(z)
    remaining = _ZONE_RE.sub(" ", text)

    # 2단계: 나머지 텍스트 공백/구두점 분리 + 조사 제거 변형 추가
    for w in re.split(r'[\s\?!,.·「」『』【】\(\)]+', remaining):
        if len(w) < 2:
            continue
        _add(w)
        _add(_PARTICLE.sub("", w))

    return result


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _search_laws(question: str) -> list[dict]:
    tokens = _tokenize(question)
    if not tokens:
        return []

    conn = get_connection()
    try:
        def _run(fts_q: str) -> list:
            try:
                return conn.execute(
                    "SELECT l.id, l.title, l.article_no, l.content "
                    "FROM laws_fts f JOIN laws l ON l.id = f.rowid "
                    "WHERE laws_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_q, _TOP_K),
                ).fetchall()
            except Exception:
                return []

        # AND 검색 (정확도 우선)
        rows = _run(" ".join(f'"{t}"' for t in tokens))

        # AND 실패 시 OR 검색 (재현율 우선)
        if not rows and len(tokens) > 1:
            rows = _run(" OR ".join(f'"{t}"' for t in tokens))

        return [dict(r) for r in rows]
    finally:
        conn.close()


_HINT_MAP: dict[str, list[str]] = {
    "주차": ["주차장", "주차 기준", "주차 대수"],
    "높이": ["가로구역", "일조권", "사선제한"],
    "조경": ["조경 의무", "식재 기준", "대지면적"],
    "에너지": ["에너지절약계획서", "ZEB", "녹색건축"],
    "용적률": ["용적률 완화", "녹색건축 인증", "공개공지"],
}


def _build_not_found_message(question: str) -> str:
    hints: list[str] = []
    for key, suggestions in _HINT_MAP.items():
        if key in question:
            hints.extend(suggestions)
    if hints:
        return (
            "현재 DB에서 관련 조문을 찾을 수 없습니다.\n"
            f"관련 키워드로 다시 질문해보세요: {', '.join(hints)}"
        )
    return "현재 DB에서 관련 조문을 찾을 수 없습니다. 확인 불가."


def answer(question: str, image_base64: str | None = None) -> dict:
    laws = _search_laws(question)

    if not laws:
        return {
            "answer": _build_not_found_message(question),
            "source_laws": [],
            "source_law_ids": [],
            "confidence": None,
        }

    context = "\n\n".join(
        f"[{law['title']} / {law['article_no']}]\n{law['content']}"
        for law in laws
    )

    user_content: list = []
    if image_base64:
        user_content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": image_base64},
        })
    user_content.append({
        "type": "text",
        "text": f"[참고 조문]\n{context}\n\n[질문]\n{question}",
    })

    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=1024,
        temperature=0,
        system=_SYSTEM,
        messages=[{"role": "user", "content": user_content}],
    )

    answer_text = response.content[0].text
    confirmed = "확인 불가" not in answer_text
    return {
        "answer": answer_text + _DISCLAIMER,
        "source_laws": laws if confirmed else [],
        "source_law_ids": [law["id"] for law in laws] if confirmed else [],
        "confidence": None,
    }
