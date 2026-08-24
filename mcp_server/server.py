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

import os
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
from mcp.server.transport_security import TransportSecuritySettings

from services.query_engine      import answer     as _qe_answer
from services.land_info         import get_land_info as _get_land_info
from services.compliance_engine import check      as _ce_check

# stateless_http・DNS 리바인딩 방지 끄기 — arch-site-model/터읽기 배포에서 확인한 것과
# 같은 이유(kunwon-ops docs/plan-mcp-gateway.md §9). 이 서버는 독립 서비스라(다른 앱에
# mount 되지 않는다) streamable_http_path 는 기본값 "/mcp" 그대로 둔다.
mcp = FastMCP(
    "law-qa",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


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
    # 기본은 stdio(로컬 Claude Code). 컨테이너에서는 MCP_TRANSPORT=streamable-http 로 띄운다
    # — 독립 서비스라 다른 앱에 얹을 필요가 없어 arch-law-graph-mcp 와 같은 형태다.
    # 인증(Bearer 토큰)은 FastMCP 바깥에서 직접 wrap 한다 — search_laws/get_land_info/
    # compliance_report 호출마다 ANTHROPIC_API_KEY·KAKAO·LURIS 요금이 나가서 막아야 한다
    # (판단 근거: kunwon-ops 저장소 docs/plan-mcp-gateway.md §7).
    if os.getenv("MCP_TRANSPORT", "stdio") == "stdio":
        mcp.run("stdio")
    else:
        import uvicorn
        from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse

        _MCP_SHARED_KEY = os.environ.get("LAW_QA_MCP_KEY")

        # "/" 는 인증 없이 공개한다 — VWorld 등 외부 API 심사자가 "실제 서비스가 맞는지"
        # URL을 직접 열어보는데, 전체를 인증으로 막아두면(초기 버전이 그랬다) 방문자에게
        # 401만 보여서 "실사용 서비스가 아니다" 로 비칠 수 있다. 도구 자체(/mcp)는 여전히
        # 인증이 걸려 있다 — 여기서 노출하는 건 서비스 설명뿐, 기능은 아니다.
        # "/" 는 사람이 브라우저로 확인하니 HTML, "/health" 는 기계용이라 JSON 그대로 둔다.
        _PUBLIC_HTML = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<title>law-qa MCP</title>
<style>
  body{font-family:-apple-system,"Malgun Gothic",sans-serif;max-width:640px;
       margin:80px auto;padding:0 24px;color:#1a1a1a;line-height:1.6}
  h1{font-size:22px;margin-bottom:4px}
  .badge{display:inline-block;background:#eef2ff;color:#4f46e5;font-size:12px;
         padding:2px 8px;border-radius:4px;margin-bottom:16px}
  code{background:#f4f4f5;padding:2px 6px;border-radius:4px;font-size:13px}
  .meta{color:#666;font-size:14px;margin-top:24px}
</style></head><body>
  <span class="badge">MCP 서버</span>
  <h1>law-qa — 건축법규 Q&amp;A</h1>
  <p>건축법규 자연어 질의 · 용도지역 조회 · 건폐율/용적률/주차/높이/조경 종합 검토를
     Claude Code(및 다른 MCP 호스트)에서 직접 호출하는 서버입니다.</p>
  <p class="meta">
    엔드포인트: <code>/mcp</code> (Bearer 토큰 인증 필요)<br>
    사용기관: 종합건축사사무소 건원 — 사내 전용, 외부 판매 없음<br>
    문의: 김정현
  </p>
</body></html>"""

        _PUBLIC_INFO = {
            "service": "law-qa MCP",
            "description": "건축법규 자연어 질의·용도지역 조회·법규 종합 검토 — Claude Code 용 MCP 서버.",
            "mcp_endpoint": "/mcp",
            "auth": "Bearer token required on /mcp — 문의: 김정현",
        }

        class _AuthMiddleware:
            def __init__(self, app):
                self._app = app

            async def __call__(self, scope, receive, send):
                if scope["type"] != "http":
                    await self._app(scope, receive, send)
                    return
                path = scope["path"]
                if path == "/":
                    resp = HTMLResponse(_PUBLIC_HTML)
                    await resp(scope, receive, send)
                    return
                if path == "/health":
                    resp = JSONResponse(_PUBLIC_INFO)
                    await resp(scope, receive, send)
                    return
                headers = dict(scope.get("headers") or [])
                token = headers.get(b"authorization", b"").decode("latin-1")
                expected = f"Bearer {_MCP_SHARED_KEY}" if _MCP_SHARED_KEY else None
                if not expected or token != expected:
                    resp = PlainTextResponse("Unauthorized", status_code=401)
                    await resp(scope, receive, send)
                    return
                await self._app(scope, receive, send)

        _app = _AuthMiddleware(mcp.streamable_http_app())
        uvicorn.run(_app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
