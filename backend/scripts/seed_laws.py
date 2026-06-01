#!/usr/bin/env python3
"""법령 시드 데이터를 law_qa.db에 적재.

사용법:
  python -m scripts.seed_laws --dry-run   # 파싱 결과만 출력
  python -m scripts.seed_laws --commit    # 실제 저장
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from services.db_manager import get_connection, init_db

SEED_DIR = _BACKEND.parent / "seed_data"
FETCHED_AT = datetime.now().isoformat()

ARTICLE_RE = re.compile(r"(?m)^제\d+조(?:의\d+)?\([^)]*\)")
# 부칙 섹션 마커: "부칙 <제570호,2013. 2. 22.>" 등
_BULJIK_RE = re.compile(r"(?m)^부칙\s*(?:<([^>]*)>)?")
_HOSU_RE = re.compile(r"제\d+(?:-\d+)?호")


# ── 텍스트 파일 ────────────────────────────────────────────────────────────────

def _parse_articles(doc_text: str, title: str, source: str) -> list[dict]:
    art_matches = list(ARTICLE_RE.finditer(doc_text))

    # 부칙 마커 위치 → 접두어 매핑 (위치 오름차순)
    buljik = []
    for bm in _BULJIK_RE.finditer(doc_text):
        inner = bm.group(1) or ""
        ho = _HOSU_RE.search(inner)
        prefix = f"부칙 {ho.group(0)} " if ho else "부칙 "
        buljik.append((bm.start(), prefix))

    # ordered dict: 동일 article_no 중복 시 마지막(최신 개정) 우선
    seen: dict[str, dict] = {}
    for i, m in enumerate(art_matches):
        end = art_matches[i + 1].start() if i + 1 < len(art_matches) else len(doc_text)
        header = m.group(0)
        content = doc_text[m.start():end].strip()
        if not content[len(header):].strip():
            continue  # 목차 항목 — 본문 없음

        # 이 조문 직전의 마지막 부칙 마커로 섹션 판별
        article_prefix = ""
        for bpos, bprefix in buljik:
            if bpos < m.start():
                article_prefix = bprefix

        article_no = article_prefix + header
        seen[article_no] = {
            "title": title,
            "article_no": article_no,
            "content": content,
            "law_type": "statute",
            "source": source,
            "fetched_at": FETCHED_AT,
        }
    return list(seen.values())


def parse_text_file(path: Path) -> list[dict]:
    text = path.read_text(encoding="utf-8")

    if text.lstrip().startswith("==="):
        # 멀티 문서 포맷: law_extracted.txt
        doc_re = re.compile(r"^=== (.+?) ===$", re.MULTILINE)
        splits = list(doc_re.finditer(text))
        rows = []
        for i, m in enumerate(splits):
            raw = m.group(1)
            title = raw.replace(".docx", "").replace(".hwp", "").strip()
            start = m.end()
            end = splits[i + 1].start() if i + 1 < len(splits) else len(text)
            rows.extend(_parse_articles(text[start:end], title, raw))
        return rows

    # 단일 문서 포맷: law_file0.txt, law_file1.txt (파일명: 헤더)
    source, title = path.name, path.stem
    for line in text.split("\n")[:10]:
        s = line.strip()
        if s.startswith("파일명:"):
            source = s.replace("파일명:", "").strip()
        elif (
            s
            and not s.startswith("[")
            and not s.startswith("국토")
            and not s.startswith("제")
            and "파일명" not in s
            and title == path.stem
        ):
            title = s
    return _parse_articles(text, title, source)


# ── JSON 파일 ──────────────────────────────────────────────────────────────────

def _std(title: str, article_no: str, content: str, source: str) -> dict:
    return {
        "title": title,
        "article_no": article_no,
        "content": content,
        "law_type": "standard",
        "source": source,
        "fetched_at": FETCHED_AT,
    }


def parse_zone_limits(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    bcr = {k: v for k, v in data.get("building_coverage_ratio", {}).items() if not k.startswith("_")}
    far = {k: v for k, v in data.get("floor_area_ratio", {}).items() if not k.startswith("_")}
    shadow = {k: v for k, v in data.get("shadow_restriction_zone", {}).items() if not k.startswith("_")}
    rows = []
    for zone in sorted(set(bcr) | set(far)):
        parts = []
        if zone in bcr:
            parts.append(f"건폐율 한도: {bcr[zone]}%")
        if zone in far:
            parts.append(f"용적률 한도: {far[zone]}%")
        for group, applies in shadow.items():
            if group in zone:
                parts.append(f"일조권 사선제한: {'적용' if applies else '미적용'}")
                break
        content = f"{zone} / " + " / ".join(parts) + " (국토의 계획 및 이용에 관한 법률 시행령 기본값)"
        rows.append(_std("용도지역별 건폐율·용적률 기준", zone, content, path.name))
    return rows


def parse_parking(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for use, info in data.get("standards", {}).items():
        rows.append(_std("용도별 주차장 설치 기준", use, f"{use} 주차 기준: {info.get('note', '')}", path.name))
    default = data.get("default", {})
    if default.get("note"):
        rows.append(_std("용도별 주차장 설치 기준", "기타 건축물", f"기타 건축물 주차 기준: {default['note']}", path.name))
    return rows


def parse_landscape(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    exempt = data.get("exempt_below_site_area")
    if exempt:
        rows.append(_std("조경 의무 기준", "면제 기준",
                         f"대지면적 {exempt}㎡ 미만 건축물은 조경 의무 면제 (건축법 시행령 §27)", path.name))
    for use, info in data.get("by_use_override", {}).items():
        if use.startswith("_"):
            continue
        notes = [t.get("note", "") for t in info.get("thresholds", []) if t.get("note")]
        rows.append(_std("조경 의무 기준", use, f"{use} 조경 기준: " + " / ".join(notes), path.name))
    for zone_type, rates in data.get("planting_rates", {}).items():
        if zone_type.startswith("_") or not isinstance(rates, dict):
            continue
        content = (f"{zone_type}지역 식재 기준: 교목 {rates.get('tree_per_m2')}주/㎡, "
                   f"관목 {rates.get('shrub_per_m2')}주/㎡ (조경기준 고시 §7조)")
        rows.append(_std("조경 의무 기준", f"{zone_type}지역 식재", content, path.name))
    return rows


def parse_far_relief(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    pos = data.get("public_open_space", {})
    if pos:
        content = (f"공개공지 의무비율({pos['mandatory_ratio_pct']}%) 초과 제공 시 "
                   f"용적률 최대 {pos['max_relief_pct']}% 완화 ({pos.get('law', '')})")
        rows.append(_std("용적률 완화 규정", "공개공지", content, path.name))
    labels = {
        "green_building": "녹색건축 인증",
        "zero_energy": "제로에너지건축물(ZEB) 인증",
        "pilot_project": "녹색건축물 조성 시범사업",
    }
    for key, label in labels.items():
        info = data.get(key, {})
        for grade, pct in info.get("by_grade", {}).items():
            content = f"{label} {grade} 등급: 용적률 {pct}% 완화 ({info.get('law', '')})"
            rows.append(_std("용적률 완화 규정", f"{label} {grade}", content, path.name))
    caps = data.get("_caps", {})
    if caps.get("certification_sum_cap_pct"):
        content = (f"녹색건축·에너지·지능형·장수명 인증 완화 합산 최대 {caps['certification_sum_cap_pct']}%, "
                   f"공개공지 포함 전체 상한 {caps['total_overall_cap_ratio']}배")
        rows.append(_std("용적률 완화 규정", "완화 합산 상한", content, path.name))
    return rows


def parse_street_block(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for block in data.get("blocks", []):
        name = block.get("block_name", "")
        height = block.get("max_height_m")
        if not name or height is None:
            continue
        content = f"{name} 최고높이: {height}m ({block.get('source', '')}) (건축법 §60)"
        rows.append(_std("가로구역별 높이 기준", name, content, path.name))
    return rows


def parse_ordinance(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for jur in data.get("jurisdictions", []):
        jname = jur.get("name", "")
        jsource = jur.get("source", "")
        limits = jur.get("limits", {})
        bcr = {k: v for k, v in limits.get("building_coverage_ratio", {}).items() if not k.startswith("_")}
        far = {k: v for k, v in limits.get("floor_area_ratio", {}).items() if not k.startswith("_")}
        landscape = {k: v for k, v in limits.get("landscape_ratio", {}).items() if not k.startswith("_")}
        for zone in sorted(set(bcr) | set(far) | set(landscape)):
            parts = []
            if zone in bcr:
                parts.append(f"건폐율: {bcr[zone]}%")
            if zone in far:
                parts.append(f"용적률: {far[zone]}%")
            if zone in landscape:
                parts.append(f"조경률: {landscape[zone]}%")
            content = f"{jname} {zone} / " + " / ".join(parts) + f" ({jsource})"
            rows.append(_std(f"{jname} 도시계획조례 용도지역별 기준", f"{jname} {zone}", content, path.name))
    return rows


# ── 진입점 ─────────────────────────────────────────────────────────────────────

def collect_rows() -> list[dict]:
    rows: list[dict] = []
    for fname in ("law_extracted.txt", "law_file0.txt", "law_file1.txt"):
        p = SEED_DIR / fname
        if p.exists():
            rows.extend(parse_text_file(p))
    rows.extend(parse_zone_limits(SEED_DIR / "zone_limits.json"))
    rows.extend(parse_parking(SEED_DIR / "parking_standards.json"))
    rows.extend(parse_landscape(SEED_DIR / "landscape_standards.json"))
    rows.extend(parse_far_relief(SEED_DIR / "far_relief_rules.json"))
    rows.extend(parse_street_block(SEED_DIR / "street_block_heights.json"))
    rows.extend(parse_ordinance(SEED_DIR / "ordinance_seed.json"))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="파싱 결과만 출력, DB 저장 안 함")
    group.add_argument("--commit", action="store_true", help="실제 DB 저장")
    args = parser.parse_args()

    all_rows = collect_rows()

    if args.dry_run:
        by_type: dict[str, int] = {}
        for r in all_rows:
            by_type[r["law_type"]] = by_type.get(r["law_type"], 0) + 1
        print(f"파싱 결과 (DB 저장 안 함):")
        print(f"  전체: {len(all_rows)}건")
        for lt, cnt in sorted(by_type.items()):
            print(f"  {lt}: {cnt}건")
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
            print(f"신규 행 없음 - 전체 {len(all_rows)}건 이미 적재됨")
            return

        conn.executemany(
            "INSERT INTO laws (title, article_no, content, law_type, source, fetched_at) "
            "VALUES (:title, :article_no, :content, :law_type, :source, :fetched_at)",
            new_rows,
        )
        conn.commit()
        print(f"완료: {len(new_rows)}건 적재, {len(all_rows) - len(new_rows)}건 건너뜀")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
