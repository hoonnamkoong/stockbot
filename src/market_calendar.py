"""KIS 국내휴장일조회(chk-holiday) 기반 개장일 달력.

chk-holiday(TR CTCA0903R)는 BASS_DT 하루가 아니라 약 3개월치 달력을 한 번에
반환한다. 응답을 통째로 저장해두면 재조회가 거의 필요 없고, 07시 갱신 런이
하루 실패해도 이전 저장분에 오늘이 들어있다.

개장 판정에는 opnd_yn(개장일여부)만 쓴다. tr_day_yn(거래일여부)·bzdy_yn(영업일여부)은
금융기관 업무일 기준이라 주식시장 개장일과 다를 수 있다.
"""


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
