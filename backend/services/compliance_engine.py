"""건축 인허가 법규 종합 검토 엔진.

단일 Claude API 호출로 건폐율·용적률·주차·높이·조경 5개 항목을 동시 검토.
"""

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
_TOP_K_PER_TOPIC = 3

_SYSTEM = """당신은 건축법규 전문 AI 어시스턴트입니다. 반드시 아래 규칙을 따르세요.

1. [참고 조문] 안의 내용만 근거로 답변합니다. 참고 조문 외의 지식을 추가하지 않습니다.
2. 조문에 명시된 수치(건폐율·용적률·주차 대수·% 등)는 절대 임의로 변경하지 않고 원문 그대로 인용합니다.
3. 각 항목 끝에 "(출처: [법령명] [조문번호])" 형식으로 근거를 반드시 명시합니다.
4. [참고 조문]에서 확인할 수 없는 항목은 반드시 "확인 불가"라고만 표시하고 추측하지 않습니다.
5. [대지 정보]가 제공된 경우 해당 용도지역 기준을 우선 적용합니다."""

_DISCLAIMER = "참고용 정보입니다. 실제 인허가는 담당 건축사 확인 필수."

_TOPICS = [
    {"key": "건폐율",  "label": "건폐율",    "keywords": ["건폐율", "건축면적비율"]},
    {"key": "용적률",  "label": "용적률",    "keywords": ["용적률", "연면적비율"]},
    {"key": "주차",    "label": "주차대수",  "keywords": ["주차", "주차대수", "주차장"]},
    {"key": "높이",    "label": "높이 제한", "keywords": ["높이", "가로구역", "일조권"]},
    {"key": "조경",    "label": "조경",      "keywords": ["조경", "식재"]},
]

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _fts_search(keywords: list[str]) -> list[dict]:
    if not keywords:
        return []
    conn = get_connection()
    try:
        def _run(fts_q: str) -> list:
            try:
                return conn.execute(
                    "SELECT l.id, l.title, l.article_no, l.content "
                    "FROM laws_fts f JOIN laws l ON l.id = f.rowid "
                    "WHERE laws_fts MATCH ? ORDER BY rank LIMIT ?",
                    (fts_q, _TOP_K_PER_TOPIC),
                ).fetchall()
            except Exception:
                return []

        rows = _run(" ".join(f'"{k}"' for k in keywords))
        if not rows and len(keywords) > 1:
            rows = _run(" OR ".join(f'"{k}"' for k in keywords))
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _search_per_topic(zone_use: str, building_use: str) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    for topic in _TOPICS:
        keywords = list(topic["keywords"])
        if zone_use:
            keywords.append(zone_use)
        if topic["key"] == "주차" and building_use:
            keywords.append(building_use)
        results[topic["key"]] = _fts_search(keywords)
    return results


def _build_prompt(
    address: str,
    zone_use: str,
    building_use: str,
    total_floor_area: float | None,
    floors: int | None,
    laws_by_topic: dict[str, list[dict]],
) -> str:
    parts: list[str] = []

    if address or zone_use:
        land_lines = ["[대지 정보]"]
        if address:
            land_lines.append(f"주소: {address}")
        if zone_use:
            land_lines.append(f"용도지역: {zone_use}")
        parts.append("\n".join(land_lines))

    bldg_lines = ["[건물 정보]"]
    if building_use:
        bldg_lines.append(f"용도: {building_use}")
    if total_floor_area is not None:
        bldg_lines.append(f"연면적: {total_floor_area:,.0f}㎡")
    if floors is not None:
        bldg_lines.append(f"층수: {floors}층")
    parts.append("\n".join(bldg_lines))

    # 중복 제거 후 전체 조문 목록
    seen_ids: set[int] = set()
    law_lines: list[str] = ["[참고 조문]"]
    for topic in _TOPICS:
        for law in laws_by_topic.get(topic["key"], []):
            if law["id"] not in seen_ids:
                seen_ids.add(law["id"])
                law_lines.append(f"\n[{law['title']} / {law['article_no']}]\n{law['content']}")
    parts.append("\n".join(law_lines))

    headers = "\n".join(f"## {t['label']}" for t in _TOPICS)
    parts.append(
        "[검토 요청]\n"
        "위 대지·건물 정보와 참고 조문을 근거로 아래 5개 항목을 검토해주세요.\n"
        "반드시 아래 헤더를 그대로 사용하고, 확인 불가한 항목은 '확인 불가'로 표시하세요.\n\n"
        + headers
    )

    return "\n\n".join(parts)


def _parse_response(text: str, laws_by_topic: dict[str, list[dict]]) -> list[dict]:
    label_to_key = {t["label"]: t["key"] for t in _TOPICS}
    matches = list(re.finditer(r'^##\s+(.+)$', text, re.MULTILINE))

    items: list[dict] = []
    for i, m in enumerate(matches):
        label = m.group(1).strip()
        key   = label_to_key.get(label, label)
        start = m.end()
        end   = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        answer = text[start:end].strip()
        confirmed = "확인 불가" not in answer
        items.append({
            "topic": label,
            "answer": answer,
            "source_laws": laws_by_topic.get(key, []) if confirmed else [],
        })

    if not items:
        items.append({"topic": "종합", "answer": text.strip(), "source_laws": []})

    return items


def check(
    address: str = "",
    building_use: str = "",
    total_floor_area: float | None = None,
    floors: int | None = None,
) -> dict:
    """건축 법규 5개 항목 종합 검토.

    반환: { address, zone_use, items: [{topic, answer, source_laws}], disclaimer }
    """
    zone_use = ""
    resolved_address = address
    if address:
        try:
            from services.land_info import get_land_info
            info = get_land_info(address)
            if "error" not in info:
                resolved_address = info.get("address", address)
                zone_use = info.get("zone_use", "")
        except Exception:
            pass

    laws_by_topic = _search_per_topic(zone_use, building_use)

    if not any(laws_by_topic.values()):
        return {
            "address": resolved_address,
            "zone_use": zone_use,
            "items": [
                {"topic": t["label"], "answer": "현재 DB에서 확인 불가", "source_laws": []}
                for t in _TOPICS
            ],
            "disclaimer": _DISCLAIMER,
        }

    prompt = _build_prompt(
        resolved_address, zone_use, building_use, total_floor_area, floors, laws_by_topic
    )

    response = _get_client().messages.create(
        model=_MODEL,
        max_tokens=3000,
        temperature=0,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    items = _parse_response(response.content[0].text, laws_by_topic)

    return {
        "address": resolved_address,
        "zone_use": zone_use,
        "items": items,
        "disclaimer": _DISCLAIMER,
    }
