"""코스피 지수 일봉 — 네이버 siseJson.

레포에 지수 계열이 없었다(종목 데이터만 있다). 심18이 "전12M 상승률"과
"252거래일 신고가"를 보려면 지수 일봉 14개월 이상이 필요하다.

네이버 금융은 2026-09 이관 이후 `api.finance.naver.com`의 JSON 한 곳만
쓴다(src/data/naver_api.py와 같은 원천). 실패하면 값을 지어내지 않고
None을 돌려준다.
"""
from __future__ import annotations

import json

from src.core import net

_URL = ('https://api.finance.naver.com/siseJson.naver?symbol={symbol}'
        '&requestType=1&startTime={start}&endTime={end}&timeframe=day')
_HDRS = {'Referer': 'https://finance.naver.com/'}

# 252거래일 신고가 + 전 12개월 상승률을 보려면 최소 2년은 받아야 한다.
# 여유를 둬서 3년을 받는다 — 응답이 300KB 미만이라 비용이 거의 없다.
LOOKBACK_YEARS = 3


def fetch_daily(symbol='KOSPI', *, start=None, end=None, today=None,
                reasons=None):
    """{'YYYY-MM-DD': 종가}. 실패하면 (None, 사유).

    start·end를 안 주면 오늘로부터 LOOKBACK_YEARS를 받는다. `today`는
    테스트에서 시각을 고정하기 위한 것이다(get_kst_now를 import하지 않는 이유는
    이 모듈이 심이 아니라 데이터 계층이기 때문이다).
    """
    if not end or not start:
        from datetime import date
        t = today or date.today()
        end = end or t.strftime('%Y%m%d')
        start = start or ('%04d%02d%02d' % (t.year - LOOKBACK_YEARS,
                                            t.month, t.day))
    url = _URL.format(symbol=symbol, start=start, end=end)
    res = net.get(url, policy=net.BULK, target='naver', reasons=reasons,
                  headers=_HDRS)
    if res is None:
        return None, f'{symbol} fetch failed'
    try:
        rows = json.loads(res.text.replace("'", '"'))
    except ValueError:
        # 리다이렉트 끝의 HTML이 여기로 온다(2026-09-10 사고의 모양).
        return None, f'{symbol} not json'
    if not isinstance(rows, list) or len(rows) < 3:
        return None, f'{symbol} rows<3'
    out = {}
    for r in rows[1:]:
        if not isinstance(r, list) or len(r) < 5:
            continue
        d = str(r[0]).strip()
        if len(d) != 8 or not d.isdigit():
            continue
        try:
            close = float(r[4])
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue        # 0·음수 종가는 결손이다 — 채우지 않고 버린다
        out[f'{d[:4]}-{d[4:6]}-{d[6:]}'] = close
    if len(out) < 200:
        return None, f'{symbol} days<200 ({len(out)})'
    return out, None
