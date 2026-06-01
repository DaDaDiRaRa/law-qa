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


def _tokenize(text: str) -> list[str]:
    """공백/구두점으로 분리 → 조사 제거 변형도 추가."""
    raw = re.split(r'[\s\?!,.·「」『』【】\(\)]+', text)
    seen: set[str] = set()
    result: list[str] = []
    for w in raw:
        if len(w) < 2:
            continue
        for candidate in (w, _PARTICLE.sub("", w)):
            if len(candidate) >= 2 and candidate not in seen:
                seen.add(candidate)
                result.append(candidate)
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


def answer(question: str, image_base64: str | None = None) -> dict:
    laws = _search_laws(question)

    if not laws:
        return {
            "answer": "현재 DB에서 관련 조문을 찾을 수 없습니다. 확인 불가.",
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
