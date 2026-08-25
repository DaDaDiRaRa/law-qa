"""주소 → 용도지역·지구·구역 조회.

arch-law-diagnose 의 /api/land_info 를 단일 소스로 쓴다(2026-08-25 통합).
이전엔 카카오 geocode + LURIS(luris.molit.go.kr) 직접 XML 호출이었는데, LURIS 서버가
IP 를 차단해 늘 실패했다(kunwon-ops 저장소 docs/plan-mcp-gateway.md §10 실측).
arch-law-diagnose 는 VWorld+LURIS+EUM 교차검증 + 캐시까지 갖춘 유일한 구현이라, 자체
구현을 버리고 그걸 호출하도록 통일한다 — 이 파일이 카카오 지오코딩까지 겸했던 이유가
LURIS는 주소가 아니라 PNU 를 받아서였는데, arch-law-diagnose 는 주소만 줘도 알아서
지오코딩까지 하므로 이 파일에서 지오코딩 로직 자체가 필요 없어졌다
(kunwon-ops 저장소 docs/plan-app-fusion.md §3).
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND.parent / ".env")

# 배포본 기본값. 로컬에서 arch-law-diagnose 를 직접 띄워 테스트할 때만 env 로 덮어쓴다.
_LAND_INFO_URL = (
    os.getenv("ARCH_LAW_DIAGNOSE_URL", "https://arch-law-diagnose-30350777436.asia-northeast3.run.app").rstrip("/")
    + "/api/land_info"
)


def get_land_info(address: str) -> dict:
    """주소 문자열 → 대지 정보 dict.

    반환 키: address, pnu, lat, lng, zone_use, zone_district, zone_area, source
    오류 시 error 키 포함(이 형태는 arch-law-diagnose 통합 전과 동일하게 유지 —
    mcp_server/server.py 의 get_land_info 도구가 이 스키마를 그대로 소비한다).
    """
    qs = urllib.parse.urlencode({"address": address})
    req = urllib.request.Request(f"{_LAND_INFO_URL}?{qs}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        return {"error": f"arch-law-diagnose 호출 실패: {e}", "address": address}
    except json.JSONDecodeError as e:
        return {"error": f"arch-law-diagnose 응답 파싱 실패: {e}", "address": address}

    if data.get("error"):
        return {"error": data["error"], "address": address}

    return {
        "address":       address,
        "pnu":           data.get("pnu", ""),
        "lat":           data.get("lat"),
        "lng":           data.get("lon"),
        "zone_use":      data.get("zone_use", ""),
        "zone_district": data.get("zone_district", ""),
        "zone_area":     data.get("zone_area", ""),
        "source":        "arch-law-diagnose",
    }
