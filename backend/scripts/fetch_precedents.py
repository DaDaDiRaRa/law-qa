#!/usr/bin/env python3
"""법제처 DRF API로 법령해석례(expc)·판례(prec)를 수집해 law_qa.db에 적재.

사용법:
  python -m scripts.fetch_precedents --dry-run   # 파싱 결과만 출력
  python -m scripts.fetch_precedents --commit    # 실제 DB 저장
"""

import argparse
import os
import re
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

QUERIES = [
    "건축법",
    "국토의계획및이용에관한법률",
    "주차장법",
    "건축법시행령",
]

_REQ_INTERVAL = 0.5
_DISPLAY      = 100

_HTML_TAG_RE   = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s{2,}")


# ── HTTP ───────────────────────────────────────────────────────────────────────

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


# ── XML 유틸 ──────────────────────────────────────────────────────────────────

def _t(elem: ET.Element | None) -> str:
    return (elem.text or "").strip() if elem is not None else ""


def _clean(text: str) -> str:
    text = _HTML_TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


# ── 검색 → ID 목록 ────────────────────────────────────────────────────────────

def _search_ids(target: str, query: str, id_tag: str) -> list[str]:
    ids: list[str] = []
    page = 1
    while True:
        try:
            raw = _get(SEARCH_URL, {
                "OC":      LAW_API_KEY,
                "target":  target,
                "type":    "XML",
                "query":   query,
                "display": str(_DISPLAY),
                "page":    str(page),
            })
        except RuntimeError as e:
            print(f"    [{target}/{query}] 검색 실패 (page={page}): {e}")
            break
        time.sleep(_REQ_INTERVAL)

        root = ET.fromstring(raw)
        items = root.findall(target)
        if not items:
            break

        for item in items:
            elem = item.find(id_tag)
            if elem is not None and elem.text:
                ids.append(elem.text.strip())

        total = int(_t(root.find("totalCnt")) or "0")
        if page * _DISPLAY >= total:
            break
        page += 1

    return ids


# ── 공통 상세 조회 ────────────────────────────────────────────────────────────

def _fetch_detail(target: str, item_id: str) -> ET.Element | None:
    """target API에서 item_id 상세 XML 루트를 반환. 실패 또는 오류 응답 시 None."""
    try:
        raw = _get(SERVICE_URL, {
            "OC":     LAW_API_KEY,
            "target": target,
            "ID":     item_id,
            "type":   "XML",
        })
    except RuntimeError:
        return None
    time.sleep(_REQ_INTERVAL)

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None

    # 오류 응답: expc는 <LsiExpc> 루트, prec는 <LsiPrec> 루트 정상
    # "일치하는 결과 없음" 등 오류 시 <Law> 루트로 반환됨
    if root.tag == "Law":
        return None

    return root


# ── 해석례(expc) 파싱 ─────────────────────────────────────────────────────────

def _fetch_expc(item_id: str) -> dict | None:
    root = _fetch_detail("expc", item_id)
    if root is None:
        return None

    # expc 전용 추가 오류 코드 체크 (prec에는 resultCode 필드 없음)
    if _t(root.find("resultCode")) not in ("00", ""):
        return None

    안건명  = _clean(_t(root.find("안건명")))
    안건번호 = _t(root.find("안건번호"))
    질의요지 = _clean(_t(root.find("질의요지")))
    회답    = _clean(_t(root.find("회답")))

    if not (안건명 and 안건번호 and (질의요지 or 회답)):
        return None

    parts: list[str] = []
    if 질의요지:
        parts.append(f"[질의] {질의요지}")
    if 회답:
        parts.append(f"[회답] {회답}")

    return {
        "title":      안건명,
        "article_no": f"해석례 {안건번호}",
        "content":    "\n\n".join(parts),
        "law_type":   "precedent",
        "source":     f"법제처 DRF expc ID:{item_id}",
        "fetched_at": FETCHED_AT,
    }


# ── 판례(prec) 파싱 ───────────────────────────────────────────────────────────

def _fetch_prec(item_id: str) -> dict | None:
    root = _fetch_detail("prec", item_id)
    if root is None:
        return None

    사건명  = _clean(_t(root.find("사건명")))
    사건번호 = _t(root.find("사건번호"))
    판시사항 = _clean(_t(root.find("판시사항")))
    판결요지 = _clean(_t(root.find("판결요지")))
    참조조문 = _clean(_t(root.find("참조조문")))
    법원명  = _t(root.find("법원명"))
    선고일자 = _t(root.find("선고일자"))

    if not (사건명 and 사건번호 and (판시사항 or 판결요지)):
        return None

    parts: list[str] = []
    if 판시사항:
        parts.append(f"[판시사항] {판시사항}")
    if 판결요지:
        parts.append(f"[판결요지] {판결요지}")
    if 참조조문:
        parts.append(f"[참조조문] {참조조문}")

    meta  = " ".join(filter(None, [법원명, 선고일자]))
    title = f"{사건명} ({meta})" if meta else 사건명

    return {
        "title":      title,
        "article_no": 사건번호,
        "content":    "\n\n".join(parts),
        "law_type":   "precedent",
        "source":     f"법제처 DRF prec ID:{item_id}",
        "fetched_at": FETCHED_AT,
    }


# ── 전체 수집 ─────────────────────────────────────────────────────────────────

_KINDS = [
    ("expc", "법령해석례일련번호", "해석례", _fetch_expc),
    ("prec", "판례일련번호",       "판례",   _fetch_prec),
]


def collect_rows() -> list[dict]:
    if not LAW_API_KEY:
        print("오류: LAW_API_KEY 환경변수가 설정되지 않았습니다. .env를 확인하세요.")
        sys.exit(1)

    all_rows: list[dict] = []
    seen_expc: set[str] = set()
    seen_prec: set[str] = set()
    seen = {"expc": seen_expc, "prec": seen_prec}

    for query in QUERIES:
        for target, id_tag, label, fetch_fn in _KINDS:
            print(f"  [{label}/{query}] ID 검색 중...")
            ids = _search_ids(target, query, id_tag)
            new_ids = [i for i in ids if i not in seen[target]]
            seen[target].update(new_ids)
            print(f"  [{label}/{query}] {len(ids)}건 발견, 신규 {len(new_ids)}건 수집 시작")

            for i, item_id in enumerate(new_ids, 1):
                row = fetch_fn(item_id)
                if row:
                    all_rows.append(row)
                if i % 20 == 0:
                    print(f"    {label} {i}/{len(new_ids)} 처리 중...")

    return all_rows


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력, DB 저장 안 함")
    group.add_argument("--commit",  action="store_true", help="실제 DB 저장")
    args = parser.parse_args()

    print(f"수집 대상: 해석례(expc) + 판례(prec) × {len(QUERIES)}개 키워드\n")
    all_rows = collect_rows()

    if args.dry_run:
        print(f"\n파싱 결과 (DB 저장 안 함):")
        print(f"  전체: {len(all_rows)}건 (law_type=precedent)")
        if all_rows:
            print("\n  샘플 (처음 3건):")
            for r in all_rows[:3]:
                print(f"    [{r['article_no']}] {r['title'][:60]}")
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


if __name__ == "__main__":
    main()
