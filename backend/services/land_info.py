"""주소 → 용도지역·지구·구역 조회.

카카오 로컬 API로 주소를 좌표·PNU로 변환하고,
LURIS 행위제한 API로 해당 필지의 용도지역 정보를 조회한다.
"""

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# 한국 정부 API 서버의 SSL 인증서 호스트명 불일치 우회용
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from dotenv import load_dotenv
load_dotenv(_BACKEND.parent / ".env")

KAKAO_API_KEY = os.getenv("KAKAO_API_KEY", "")
LURIS_API_KEY = os.getenv("LURIS_API_KEY", "")

_KAKAO_URL = "https://dapi.kakao.com/v2/local/search/address.json"
_LURIS_URL  = "https://luris.molit.go.kr/system/LurisService"


def _geocode(address: str) -> dict:
    """카카오 로컬 API: 주소 → 위경도 + 법정동 코드."""
    if not KAKAO_API_KEY:
        raise RuntimeError("KAKAO_API_KEY가 설정되지 않았습니다.")

    qs  = urllib.parse.urlencode({"query": address, "analyze_type": "similar"}, encoding="utf-8")
    req = urllib.request.Request(
        f"{_KAKAO_URL}?{qs}",
        headers={"Authorization": f"KakaoAK {KAKAO_API_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"카카오 API 호출 실패: {e}") from e

    docs = data.get("documents", [])
    if not docs:
        raise RuntimeError(f"주소를 찾을 수 없습니다: {address!r}")

    doc  = docs[0]
    addr = doc.get("address") or {}

    b_code   = addr.get("b_code", "")
    main_no  = addr.get("main_address_no", "0") or "0"
    sub_no   = addr.get("sub_address_no",  "0") or "0"
    mountain = "1" if addr.get("mountain_yn", "N") == "Y" else "0"

    # PNU = 법정동코드(10) + 산여부(1) + 본번(4) + 부번(4) = 19자리
    try:
        pnu = f"{b_code}{mountain}{int(main_no):04d}{int(sub_no):04d}" if b_code else ""
    except ValueError:
        pnu = ""

    return {
        "address_name": doc.get("address_name", address),
        "lat": float(doc.get("y", 0) or 0),
        "lng": float(doc.get("x", 0) or 0),
        "b_code": b_code,
        "pnu": pnu,
    }


def _zone_from_luris(pnu: str) -> dict:
    """LURIS 행위제한 API: PNU → 용도지역·지구·구역."""
    if not LURIS_API_KEY:
        raise RuntimeError("LURIS_API_KEY가 설정되지 않았습니다.")
    if not pnu:
        raise RuntimeError("PNU 코드가 없습니다.")

    qs  = urllib.parse.urlencode({"apiKey": LURIS_API_KEY, "pnu": pnu, "scale": 1000})
    req = urllib.request.Request(f"{_LURIS_URL}?{qs}")
    try:
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CTX) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        raise RuntimeError(f"LURIS API 호출 실패: {e}") from e

    # JSON 우선, 실패 시 XML 시도
    try:
        data  = json.loads(raw.decode("utf-8"))
        items = data.get("resultList") or data.get("result") or []
        item  = items[0] if isinstance(items, list) and items else (items if isinstance(items, dict) else {})
        return {
            "zone_use":      item.get("prposAreaDstrctnNm",  ""),
            "zone_district": item.get("prposAreaDstrctnNm2", ""),
            "zone_area":     item.get("prposAreaDstrctnNm3", ""),
        }
    except (json.JSONDecodeError, KeyError):
        pass

    try:
        root = ET.fromstring(raw)

        def _t(e: ET.Element | None) -> str:
            return (e.text or "").strip() if e is not None else ""

        item = root.find(".//item") or root
        return {
            "zone_use":      _t(item.find("prposAreaDstrctnNm")),
            "zone_district": _t(item.find("prposAreaDstrctnNm2")),
            "zone_area":     _t(item.find("prposAreaDstrctnNm3")),
        }
    except ET.ParseError as e:
        raise RuntimeError(f"LURIS 응답 파싱 실패: {e}") from e


def get_land_info(address: str) -> dict:
    """주소 문자열 → 대지 정보 dict.

    반환 키: address, pnu, lat, lng, zone_use, zone_district, zone_area, source
    오류 시 error 키 포함.
    """
    try:
        geo = _geocode(address)
    except RuntimeError as e:
        return {"error": str(e), "address": address}

    result: dict = {
        "address":       geo["address_name"],
        "pnu":           geo["pnu"],
        "lat":           geo["lat"],
        "lng":           geo["lng"],
        "zone_use":      "",
        "zone_district": "",
        "zone_area":     "",
    }

    try:
        zone = _zone_from_luris(geo["pnu"])
        result.update(zone)
        result["source"] = "카카오 + LURIS"
    except RuntimeError as e:
        result["source"] = f"카카오 좌표 조회 완료; 용도지역 조회 실패: {e}"

    return result
