#!/usr/bin/env python3
"""건축 인허가 관련 부수법령을 법제처 DRF API로 수집 후 law_qa.db에 적재.

사용법:
  python -m scripts.fetch_supplementary --dry-run
  python -m scripts.fetch_supplementary --commit
"""

import argparse
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND.parent / ".env")

from services.db_manager import get_connection, init_db

LAW_API_KEY = os.getenv("LAW_API_KEY", "")
SEARCH_URL  = "https://www.law.go.kr/DRF/lawSearch.do"
SERVICE_URL = "https://www.law.go.kr/DRF/lawService.do"
FETCHED_AT  = datetime.now().isoformat()

# 건축 인허가 부수법령 수집 대상
# 대기환경보전법 시행령·소음진동관리법 시행령은 전문 수집 후
# FTS 검색 시 건축 관련 조문이 자연스럽게 필터링됨
TARGETS = [
    "소방시설 설치 및 관리에 관한 법률",
    "소방시설 설치 및 관리에 관한 법률 시행령",
    "장애인·노인·임산부 등의 편의증진 보장에 관한 법률",
    "장애인·노인·임산부 등의 편의증진 보장에 관한 법률 시행령",
    "산지관리법",
    "산지관리법 시행령",
    "도로법",
    "도로법 시행령",
    "하수도법",
    "하수도법 시행령",
    "수도법",
    "수도법 시행령",
    "자연재해대책법",
    "자연재해대책법 시행령",
    "문화재보호법",
    "문화재보호법 시행령",
    "군사기지 및 군사시설 보호법",
    "학교보건법",
    "학교보건법 시행령",
    "대기환경보전법 시행령",
    "소음·진동관리법 시행령",
]

_REQ_INTERVAL = 0.5


# ── HTTP ──────────────────────────────────────────────────────────────────────

def _get(url: str, params: dict) -> bytes:
    qs = urllib.parse.urlencode(params, encoding="utf-8")
    req = urllib.request.Request(
        f"{url}?{qs}",
        headers={"User-Agent": "law-qa-fetcher/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"API 호출 실패: {e}") from e


# ── XML 유틸 ─────────────────────────────────────────────────────────────────

def _t(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


# ── 법령 MST 검색 ─────────────────────────────────────────────────────────────

def _find_mst(law_name: str) -> str | None:
    """법령명으로 MST 검색. 정확히 일치하는 항목만 반환."""
    data = _get(SEARCH_URL, {
        "OC":      LAW_API_KEY,
        "target":  "law",
        "type":    "XML",
        "query":   law_name,
        "display": "10",
        "sort":    "efYd",
    })
    time.sleep(_REQ_INTERVAL)

    root = ET.fromstring(data)
    for elem in root.findall("law"):
        if _t(elem.find("법령명한글")) == law_name:
            mst = _t(elem.find("법령일련번호")) or _t(elem.find("MST"))
            return mst if mst else None
    return None


# ── 조문 파싱 ─────────────────────────────────────────────────────────────────

def _build_article_no(조번호: str, 조문제목: str, prefix: str = "") -> str:
    base = f"제{조번호}조"
    article = f"{base}({조문제목})" if 조문제목 else base
    return f"{prefix}{article}"


def _collect_unit(
    unit: ET.Element, prefix: str, title: str, source: str
) -> dict | None:
    if _t(unit.find("조문여부")) not in ("조문", ""):
        return None

    조번호   = _t(unit.find("조문번호")) or _t(unit.find("조번호"))
    조문제목 = _t(unit.find("조문제목"))
    조문내용 = _t(unit.find("조문내용"))

    if not 조번호:
        return None

    article_no = _build_article_no(조번호, 조문제목, prefix)

    if 조문내용.startswith(f"제{조번호}조"):
        lines = [조문내용]
    else:
        header = _build_article_no(조번호, 조문제목)
        lines = [f"{header} {조문내용}".strip() if 조문내용 else header]

    for 항 in unit.findall("항"):
        항번호 = _t(항.find("항번호"))
        항내용 = _t(항.find("항내용"))
        if 항내용:
            lines.append(f"{항번호} {항내용}".strip())
        for 호 in 항.findall("호"):
            호번호 = _t(호.find("호번호"))
            호내용 = _t(호.find("호내용"))
            if 호내용:
                lines.append(f"  {호번호} {호내용}".strip())

    content = "\n".join(lines).strip()
    if not content:
        return None

    return {
        "title":      title,
        "article_no": article_no,
        "content":    content,
        "law_type":   "supplementary",
        "source":     source,
        "fetched_at": FETCHED_AT,
    }


def _parse_law(xml_bytes: bytes, law_name: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"    XML 파싱 오류: {e}")
        return []

    title = _t(root.find("기본정보/법령명_한글")) or law_name
    seen: dict[str, dict] = {}

    for unit in root.findall("조문/조문단위"):
        row = _collect_unit(unit, "", title, source)
        if row:
            seen[row["article_no"]] = row

    for 부칙단위 in root.findall("부칙/부칙단위"):
        공포번호 = _t(부칙단위.find("공포번호")) or _t(부칙단위.find("부칙공포번호"))
        prefix = f"부칙<{공포번호}> " if 공포번호 else "부칙 "
        for unit in 부칙단위.findall(".//조문단위"):
            row = _collect_unit(unit, prefix, title, source)
            if row:
                seen[row["article_no"]] = row

    return list(seen.values())


# ── 단일 법령 수집 ────────────────────────────────────────────────────────────

def fetch_law(law_name: str) -> list[dict]:
    print(f"  [{law_name}] MST 검색 중...")
    try:
        mst = _find_mst(law_name)
    except RuntimeError as e:
        print(f"  [{law_name}] 검색 실패: {e}")
        return []

    if not mst:
        print(f"  [{law_name}] 일치하는 법령을 찾을 수 없음 - 건너뜀")
        return []

    print(f"  [{law_name}] MST={mst} 전문 수집 중...")
    source = f"법제처 DRF MST:{mst}"
    try:
        xml_bytes = _get(SERVICE_URL, {
            "OC":     LAW_API_KEY,
            "target": "law",
            "type":   "XML",
            "MST":    mst,
        })
    except RuntimeError as e:
        print(f"  [{law_name}] 수집 실패: {e}")
        return []
    time.sleep(_REQ_INTERVAL)

    rows = _parse_law(xml_bytes, law_name, source)
    print(f"  [{law_name}] 조문 {len(rows)}개 파싱 완료")
    return rows


# ── 진입점 ────────────────────────────────────────────────────────────────────

def collect_rows() -> list[dict]:
    if not LAW_API_KEY:
        print("오류: LAW_API_KEY 환경변수가 설정되지 않았습니다. .env를 확인하세요.")
        sys.exit(1)

    all_rows: list[dict] = []
    for name in TARGETS:
        all_rows.extend(fetch_law(name))
    return all_rows


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력, DB 저장 안 함")
    group.add_argument("--commit",  action="store_true", help="실제 DB 저장")
    args = parser.parse_args()

    print(f"수집 대상: {len(TARGETS)}개 부수법령\n")
    all_rows = collect_rows()

    if args.dry_run:
        by_law: dict[str, int] = {}
        for r in all_rows:
            by_law[r["title"]] = by_law.get(r["title"], 0) + 1
        print(f"\n파싱 결과 (DB 저장 안 함):")
        print(f"  전체: {len(all_rows)}건")
        for law, cnt in by_law.items():
            print(f"  {law}: {cnt}건")
        return

    init_db()
    conn = get_connection()
    try:
        existing = {
            (r[0], r[1])
            for r in conn.execute("SELECT title, article_no FROM laws").fetchall()
        }
        new_rows = [r for r in all_rows if (r["title"], r["article_no"]) not in existing]

        if not new_rows:
            print(f"\n신규 행 없음 - 전체 {len(all_rows)}건 이미 적재됨")
            return

        conn.executemany(
            "INSERT INTO laws (title, article_no, content, law_type, source, fetched_at) "
            "VALUES (:title, :article_no, :content, :law_type, :source, :fetched_at)",
            new_rows,
        )
        conn.commit()
        print(f"\n완료: {len(new_rows)}건 적재, {len(all_rows) - len(new_rows)}건 건너뜀")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
