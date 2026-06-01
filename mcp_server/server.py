#!/usr/bin/env python3
"""law-qa MCP 서버.

backend/services/ 를 직접 import — 서비스 로직 변경 시 MCP 도구에 자동 반영.

## Claude Code에 연결하는 방법

터미널에서 한 번만 실행:
  claude mcp add law-qa python d:/APPS/law-qa/mcp_server/server.py

## 노출 도구

- search_laws       : 자연어 건축법령 검색
- get_land_info     : 주소 → 용도지역 조회
- compliance_report : 건폐율·용적률·주차·높이·조경 5개 항목 종합 검토
"""

import sys
from pathlib import Path
from typing import Optional

_ROOT    = Path(__file__).resolve().parent.parent
_BACKEND = _ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from mcp.server.fastmcp import FastMCP

from services.query_engine      import answer     as _qe_answer
from services.land_info         import get_land_info as _get_land_info
from services.compliance_engine import check      as _ce_check

mcp = FastMCP("law-qa")


@mcp.tool()
def search_laws(question: str) -> str:
    """건축법령 DB에서 자연어 질문에 관련된 조문을 검색하고 답변합니다.
    특정 법규 기준·조문 내용·수치 확인 시 사용하세요.
    질문 안에 주소(예: 강남구 삼성동)가 포함되면 용도지역을 자동으로 조회합니다.
    """
    result = _qe_answer(question)
    answer_text = result["answer"]

    source_laws = result.get("source_laws", [])
    if source_laws:
        refs = "\n\n".join(
            f"[{l['title']} / {l['article_no']}]\n{l['content']}"
            for l in source_laws
        )
        return f"{answer_text}\n\n---\n[참고 조문]\n{refs}"

    return answer_text


@mcp.tool()
def get_land_info(address: str) -> str:
    """주소로 해당 토지의 용도지역·용도지구·용도구역을 조회합니다.
    건축 검토 전 대지 기본 정보 확인 시 사용하세요.
    """
    info = _get_land_info(address)

    if "error" in info:
        return f"조회 실패: {info['error']}"

    lines = [f"주소: {info.get('address', address)}"]
    if info.get("zone_use"):
        lines.append(f"용도지역: {info['zone_use']}")
    if info.get("zone_district"):
        lines.append(f"용도지구: {info['zone_district']}")
    if info.get("zone_area"):
        lines.append(f"용도구역: {info['zone_area']}")
    if info.get("pnu"):
        lines.append(f"PNU: {info['pnu']}")
    lines.append(f"출처: {info.get('source', '')}")

    return "\n".join(lines)


@mcp.tool()
def compliance_report(
    address: str = "",
    building_use: str = "",
    total_floor_area: Optional[float] = None,
    floors: Optional[int] = None,
) -> str:
    """건물 정보를 입력받아 건폐율·용적률·주차·높이·조경 5개 항목을 한 번에 검토합니다.
    주소 입력 시 용도지역을 자동 조회하여 해당 기준을 우선 적용합니다.
    """
    result = _ce_check(
        address=address,
        building_use=building_use,
        total_floor_area=total_floor_area,
        floors=floors,
    )

    lines: list[str] = []

    if result.get("address") or result.get("zone_use"):
        lines.append("[대지 정보]")
        if result.get("address"):
            lines.append(f"주소: {result['address']}")
        if result.get("zone_use"):
            lines.append(f"용도지역: {result['zone_use']}")
        lines.append("")

    for item in result.get("items", []):
        lines.append(f"## {item['topic']}")
        lines.append(item["answer"])
        laws = item.get("source_laws", [])
        if laws:
            lines.append(
                "근거: " + ", ".join(f"{l['title']} {l['article_no']}" for l in laws)
            )
        lines.append("")

    lines.append(result.get("disclaimer", ""))

    return "\n".join(lines).strip()


if __name__ == "__main__":
    mcp.run()
