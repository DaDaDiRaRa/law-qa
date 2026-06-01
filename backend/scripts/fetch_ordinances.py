#!/usr/bin/env python3
"""법제처 DRF API로 광역시·도 자치법규(조례) 수집 후 law_qa.db에 적재.

사용법:
  python -m scripts.fetch_ordinances --dry-run
  python -m scripts.fetch_ordinances --commit
  python -m scripts.fetch_ordinances --sido 서울특별시 --commit
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

SIDO_LIST = [
    "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시",
    "대전광역시", "울산광역시", "세종특별자치시", "경기도", "강원특별자치도",
    "충청북도", "충청남도", "전북특별자치도", "전라남도", "경상북도", "경상남도",
    "제주특별자치도",
]

ORDIN_PATTERNS = [
    "{sido} 도시계획 조례",
    "{sido} 건축 조례",
    "{sido} 주차장 설치 및 관리 조례",
    "{sido} 건축위원회 조례",
]

# 시군구 단위 목록 (시도 → 시군구 리스트)
SIGUNGU_BY_SIDO: dict[str, list[str]] = {
    "서울특별시": [
        "강남구", "강동구", "강북구", "강서구", "관악구",
        "광진구", "구로구", "금천구", "노원구", "도봉구",
        "동대문구", "동작구", "마포구", "서대문구", "서초구",
        "성동구", "성북구", "송파구", "양천구", "영등포구",
        "용산구", "은평구", "종로구", "중구", "중랑구",
    ],
}

# 시군구 조례 검색 패턴 (도시계획·건축위원회는 광역 관할이라 제외)
# 법제처 DB는 "{시도} {시군구} 건축 조례" 형태로 등록됨
SIGUNGU_PATTERNS = [
    "{sido} {sigungu} 건축 조례",
    "{sido} {sigungu} 주차장 설치 및 관리 조례",
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


def _get_title(root: ET.Element, fallback: str) -> str:
    for path in ("기본정보/법령명_한글", "기본정보/자치법규명_한글"):
        val = _t(root.find(path))
        if val:
            return val
    return fallback


# ── 조례 MST 검색 ─────────────────────────────────────────────────────────────

def _ordin_fields(elem: ET.Element) -> tuple[str, str]:
    """조례 검색 결과에서 (이름, MST) 추출.

    법제처 DRF API는 target=ordin일 때 필드명이 국가법령과 다름:
      이름: 자치법규명  (국가법령: 법령명한글)
      MST : 자치법규일련번호  (국가법령: MST)
    """
    name = _t(elem.find("자치법규명")) or _t(elem.find("법령명한글"))
    mst  = _t(elem.find("자치법규일련번호")) or _t(elem.find("MST"))
    return name, mst


def _find_mst(query: str, sido: str) -> tuple[str, str] | None:
    """조례명으로 (MST, 실제 법령명) 검색.

    우선순위: 정확 일치 → 시도/시군구명을 포함한 첫 번째 결과.
    둘 다 없으면 None.
    """
    data = _get(SEARCH_URL, {
        "OC":      LAW_API_KEY,
        "target":  "ordin",
        "type":    "XML",
        "query":   query,
        "display": "5",
        "sort":    "efYd",
    })
    time.sleep(_REQ_INTERVAL)

    root = ET.fromstring(data)
    laws = root.findall("law")
    if not laws:
        return None

    # 1순위: 정확 일치
    for elem in laws:
        name, mst = _ordin_fields(elem)
        if name == query:
            return (mst, name) if mst else None

    # 2순위: 시도/시군구명 + 핵심 카테고리 단어 포함 (행정 지명어 제외)
    _ADMIN_SUFFIXES = ("특별시", "광역시", "특별자치시", "특별자치도", "도", "구", "시", "군")
    category_words = [
        w for w in query.split()
        if w != "조례" and w != sido
        and not any(w.endswith(s) for s in _ADMIN_SUFFIXES)
    ]
    for elem in laws:
        name, mst = _ordin_fields(elem)
        if sido not in name:
            continue
        # 카테고리 단어가 단독 단어로 포함되어야 함 (공백 구분 기준)
        name_words = set(name.replace("·", " ").replace("「", " ").replace("」", " ").split())
        if any(w in name_words for w in category_words):
            return (mst, name) if mst else None

    return None


# ── 조문 파싱 ─────────────────────────────────────────────────────────────────

def _build_article_no(조번호: str, 조문제목: str, prefix: str = "") -> str:
    base = f"제{조번호}조"
    article = f"{base}({조문제목})" if 조문제목 else base
    return f"{prefix}{article}"


def _collect_unit(
    unit: ET.Element, prefix: str, title: str, source: str
) -> dict | None:
    조번호   = _t(unit.find("조번호"))
    조문제목 = _t(unit.find("조문제목"))
    조문내용 = _t(unit.find("조문내용"))

    if not 조번호:
        return None

    article_no = _build_article_no(조번호, 조문제목, prefix)

    # 조문내용이 이미 헤더를 포함하면 그대로, 아니면 헤더 앞에 붙임
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
        "law_type":   "ordinance",
        "source":     source,
        "fetched_at": FETCHED_AT,
    }


def _parse_ordin_jo(root: ET.Element, title: str, source: str) -> dict[str, dict]:
    """자치법규 서비스 XML 스키마: 조문/조 → 조문번호·조제목·조내용."""
    seen: dict[str, dict] = {}
    for 조 in root.findall("조문/조"):
        if _t(조.find("조문여부")) == "N":
            continue
        번호_raw = _t(조.find("조문번호"))
        제목 = _t(조.find("조제목"))
        내용 = _t(조.find("조내용"))
        if not 번호_raw or not 내용:
            continue
        try:
            num = int(번호_raw) // 100
        except ValueError:
            continue
        article_no = f"제{num}조({제목})" if 제목 else f"제{num}조"
        seen[article_no] = {
            "title":      title,
            "article_no": article_no,
            "content":    내용,
            "law_type":   "ordinance",
            "source":     source,
            "fetched_at": FETCHED_AT,
        }
    return seen


def _parse_ordinance(xml_bytes: bytes, title_fallback: str, source: str) -> list[dict]:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        print(f"    XML 파싱 오류: {e}")
        return []

    title = _get_title(root, title_fallback)
    seen: dict[str, dict] = {}

    # 자치법규 서비스 스키마 (조문/조)
    if root.findall("조문/조"):
        seen.update(_parse_ordin_jo(root, title, source))
        return list(seen.values())

    # 기존 국가법령 스키마 (조문/조문단위)
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


# ── 단일 조례 수집 ────────────────────────────────────────────────────────────

def fetch_ordinance(query: str, sido: str) -> list[dict]:
    """조례 하나를 검색·수집·파싱. MST 없으면 빈 리스트, 수집 실패 시 RuntimeError."""
    result = _find_mst(query, sido)
    if not result:
        return []

    mst, actual_name = result
    source = f"법제처 DRF(조례) MST:{mst}"

    xml_bytes = _get(SERVICE_URL, {
        "OC":     LAW_API_KEY,
        "target": "ordin",
        "type":   "XML",
        "MST":    mst,
    })
    time.sleep(_REQ_INTERVAL)

    return _parse_ordinance(xml_bytes, actual_name, source)


# ── 전체 수집 ─────────────────────────────────────────────────────────────────

def collect_rows(sido_filter: str | None = None) -> tuple[list[dict], list[str]]:
    """모든 시도·조례 조합 수집. 반환: (rows, failure_logs)"""
    targets = [s for s in SIDO_LIST if sido_filter is None or s == sido_filter]
    if sido_filter and not targets:
        print(f"오류: '{sido_filter}'은 지원하는 시도 목록에 없습니다.")
        print(f"지원 목록: {', '.join(SIDO_LIST)}")
        sys.exit(1)

    all_rows: list[dict] = []
    failures: list[str]  = []
    total = len(targets) * len(ORDIN_PATTERNS)
    done  = 0

    for sido in targets:
        for pattern in ORDIN_PATTERNS:
            query = pattern.format(sido=sido)
            done += 1
            print(f"  [{done:>3}/{total}] {query}")
            try:
                rows = fetch_ordinance(query, sido)
            except RuntimeError as e:
                msg = f"{query} — {e}"
                print(f"    수집 실패: {msg}")
                failures.append(f"[수집 실패] {msg}")
                continue

            if rows:
                print(f"    조문 {len(rows)}개")
                all_rows.extend(rows)
            else:
                msg = f"{query}"
                print(f"    검색 결과 없음")
                failures.append(f"[결과 없음] {msg}")

    return all_rows, failures


def collect_sigungu_rows(sido_filter: str | None = None) -> tuple[list[dict], list[str]]:
    """시군구 단위 조례 수집. 반환: (rows, failure_logs)"""
    if sido_filter and sido_filter not in SIGUNGU_BY_SIDO:
        print(f"오류: '{sido_filter}'의 시군구 목록이 없습니다.")
        print(f"지원 시도: {', '.join(SIGUNGU_BY_SIDO.keys())}")
        sys.exit(1)

    targets: list[tuple[str, str]] = []  # (sido, sigungu)
    for sido, gulist in SIGUNGU_BY_SIDO.items():
        if sido_filter is None or sido == sido_filter:
            for gu in gulist:
                targets.append((sido, gu))

    all_rows: list[dict] = []
    failures: list[str]  = []
    total = len(targets) * len(SIGUNGU_PATTERNS)
    done  = 0

    for sido, sigungu in targets:
        for pattern in SIGUNGU_PATTERNS:
            query = pattern.format(sido=sido, sigungu=sigungu)
            done += 1
            print(f"  [{done:>3}/{total}] {query}")
            try:
                rows = fetch_ordinance(query, sigungu)
            except RuntimeError as e:
                msg = f"{query} — {e}"
                print(f"    수집 실패: {msg}")
                failures.append(f"[수집 실패] {msg}")
                continue

            if rows:
                print(f"    조문 {len(rows)}개")
                all_rows.extend(rows)
            else:
                print(f"    검색 결과 없음")
                failures.append(f"[결과 없음] {query}")

    return all_rows, failures


# ── 진입점 ────────────────────────────────────────────────────────────────────

def _save_to_db(all_rows: list[dict]) -> None:
    init_db()
    conn = get_connection()
    try:
        existing = {
            (r[0], r[1])
            for r in conn.execute("SELECT title, article_no FROM laws").fetchall()
        }
        new_rows = [r for r in all_rows if (r["title"], r["article_no"]) not in existing]

        if not new_rows:
            print(f"\n신규 행 없음 — 전체 {len(all_rows)}건 이미 적재됨")
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


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력, DB 저장 안 함")
    group.add_argument("--commit",  action="store_true", help="실제 DB 저장")
    parser.add_argument("--sido",    metavar="시도명",   help="특정 시도만 수집 (예: 서울특별시)")
    parser.add_argument("--sigungu", metavar="시도명",   help="시군구 단위 수집 (예: 서울특별시)")
    args = parser.parse_args()

    if not LAW_API_KEY:
        print("오류: LAW_API_KEY 환경변수가 설정되지 않았습니다. .env를 확인하세요.")
        sys.exit(1)

    if "--sigungu" in sys.argv:
        # 시군구 모드
        sido_filter = args.sigungu or None
        label = f" ({sido_filter} 시군구)" if sido_filter else " (전체 시군구)"
        gucount = len(SIGUNGU_BY_SIDO.get(sido_filter, [])) if sido_filter else sum(len(v) for v in SIGUNGU_BY_SIDO.values())
        print(f"수집 대상: {gucount}개 시군구 × {len(SIGUNGU_PATTERNS)}개 조례 패턴{label}\n")
        all_rows, failures = collect_sigungu_rows(sido_filter)
    else:
        # 광역시·도 모드 (기존)
        targets_n  = 1 if args.sido else len(SIDO_LIST)
        sido_label = f" ({args.sido})" if args.sido else ""
        print(f"수집 대상: {targets_n}개 시도 × {len(ORDIN_PATTERNS)}개 조례 패턴{sido_label}\n")
        all_rows, failures = collect_rows(args.sido)

    if failures:
        print(f"\n{'─'*60}")
        print(f"수집 실패 / 결과 없음 ({len(failures)}건):")
        for f in failures:
            print(f"  {f}")

    if args.dry_run:
        by_law: dict[str, int] = {}
        for r in all_rows:
            by_law[r["title"]] = by_law.get(r["title"], 0) + 1
        print(f"\n파싱 결과 (DB 저장 안 함):")
        print(f"  전체: {len(all_rows)}건")
        for law, cnt in by_law.items():
            print(f"  {law}: {cnt}건")
        return

    if not all_rows:
        print("\n적재할 조문이 없습니다.")
        return

    _save_to_db(all_rows)


if __name__ == "__main__":
    main()
