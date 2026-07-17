"""KIS 국내휴장일조회(chk-holiday) 기반 개장일 달력.

chk-holiday(TR CTCA0903R)는 BASS_DT 하루가 아니라 약 3개월치 달력을 한 번에
반환한다. 응답을 통째로 저장해두면 재조회가 거의 필요 없고, 07시 갱신 런이
하루 실패해도 이전 저장분에 오늘이 들어있다.

개장 판정에는 opnd_yn(개장일여부)만 쓴다. tr_day_yn(거래일여부)·bzdy_yn(영업일여부)은
금융기관 업무일 기준이라 주식시장 개장일과 다를 수 있다.
"""

import json
import os
from datetime import datetime, timedelta

import requests

CALENDAR_PATH = 'data/market_calendar.json'
TOKEN_CACHE_PATH = 'data/kis_token_cache.json'
CHK_HOLIDAY_URL = (
    "https://openapi.koreainvestment.com:9443"
    "/uapi/domestic-stock/v1/quotations/chk-holiday"
)


def parse_calendar(api_response: dict) -> dict:
    """chk-holiday 응답에서 {bass_dt: opnd_yn} 맵을 뽑는다.

    두 필드 중 하나라도 비면 그 행은 버린다 (가짜 판정 금지).
    """
    days = {}
    for row in api_response.get('output', []):
        bass_dt = row.get('bass_dt', '')
        opnd_yn = row.get('opnd_yn', '')
        if bass_dt and opnd_yn:
            days[bass_dt] = opnd_yn
    return days


def lookup(days: dict, yyyymmdd: str):
    """개장 여부. True=개장, False=휴장, None=판정 불가(달력에 없음)."""
    value = days.get(yyyymmdd)
    if value == 'Y':
        return True
    if value == 'N':
        return False
    return None


def fetch_calendar(access_token: str, app_key: str, app_secret: str,
                   base_date: str) -> dict:
    """chk-holiday를 호출해 base_date부터의 달력을 받는다.

    실패는 예외다. 빈 달력으로 폴백하면 판정 불가가 개장으로 둔갑한다.
    """
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": "CTCA0903R",
        "custtype": "P",
    }
    params = {"BASS_DT": base_date, "CTX_AREA_NK": "", "CTX_AREA_FK": ""}

    res = requests.get(CHK_HOLIDAY_URL, headers=headers, params=params, timeout=10)
    res.raise_for_status()
    data = res.json()

    if data.get('rt_cd') != '0':
        raise RuntimeError(f"chk-holiday 오류: {data.get('msg1', '')}")

    days = parse_calendar(data)
    if not days:
        raise RuntimeError("chk-holiday 응답의 달력이 비어 있다")
    return days


def load_calendar(path: str = None) -> dict:
    """저장된 달력을 읽는다. 없거나 깨졌으면 빈 맵."""
    try:
        with open(path or CALENDAR_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('days', {})
    except Exception:
        return {}


def save_calendar(days: dict, path: str = None) -> None:
    """달력을 저장한다. updated_at은 디버깅용이며 판정에 쓰지 않는다."""
    target = path or CALENDAR_PATH
    payload = {
        'updated_at': (datetime.utcnow() + timedelta(hours=9)).isoformat(),
        'days': days,
    }
    parent = os.path.dirname(target)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(target, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def load_access_token(path: str = None) -> str:
    """token_manager가 남긴 로컬 캐시에서 토큰을 읽는다. 없으면 None."""
    try:
        with open(path or TOKEN_CACHE_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('access_token')
    except Exception:
        return None


def refresh_calendar(base_date: str) -> dict:
    """달력을 조회해 저장하고 반환한다. 실패는 예외."""
    app_key = os.environ.get('KIS_APP_KEY', '').strip()
    app_secret = os.environ.get('KIS_APP_SECRET', '').strip()
    if not app_key or not app_secret:
        raise RuntimeError("KIS_APP_KEY/KIS_APP_SECRET가 없다")

    token = load_access_token()
    if not token:
        raise RuntimeError("KIS 토큰 캐시가 없다")

    days = fetch_calendar(token, app_key, app_secret, base_date)
    save_calendar(days)
    return days
