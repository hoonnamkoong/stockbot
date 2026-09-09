"""Yahoo Finance 비공식 chart API — 일봉과 현재가.

scripts/fetch_us_market.py가 지수 4개로 이미 키 없이 안정 작동을 확인한
같은 엔드포인트다. 여기서는 종목 단위로 OHLCV 전체(그 스크립트는 종가만)와
현재가(meta.regularMarketPrice)를 뽑는다.

SLA가 없는 비공식 API라 응답 형식이 바뀌거나 IP가 막힐 수 있다 — 실패는
예외/None으로 드러내고 0으로 지어내지 않는다.
"""
import datetime as dt

from src.core import net

CHART_URL = 'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}'
HEADERS = {'User-Agent': 'Mozilla/5.0'}

_RANGE_TO_PARAMS = {
    '1y': {'range': '1y', 'interval': '1d'},
    '1d': {'range': '1d', 'interval': '1m'},
}


def _get_chart(symbol: str, range_: str) -> dict:
    params = dict(_RANGE_TO_PARAMS.get(range_, {'range': range_, 'interval': '1d'}))
    # required=True — 이 함수의 두 호출부가 계약이 다르다. `fetch_daily_ohlcv`는
    # 예외를 그대로 올려야 하고(그 종목을 판단할 수 없다는 뜻),
    # `fetch_current_quote`는 아래에서 잡아 None으로 접는다("지금 값을 모른다").
    # 여기서 None을 주면 뒤의 `['chart']` 첨자가 TypeError로 터져 이유가 사라진다.
    r = net.get(CHART_URL.format(symbol=symbol), policy=net.FAST, target='yahoo',
                params=params, headers=HEADERS, required=True)
    return r.json()['chart']['result'][0]


def fetch_daily_ohlcv(symbol: str, range_: str = '1y') -> list[dict]:
    """일봉 OHLCV. close가 없는 날짜(휴장·결측)는 건너뛴다. 실패 시 예외."""
    res = _get_chart(symbol, range_)
    timestamps = res.get('timestamp') or []
    quote = (res.get('indicators') or {}).get('quote', [{}])[0]
    opens = quote.get('open') or []
    highs = quote.get('high') or []
    lows = quote.get('low') or []
    closes = quote.get('close') or []
    volumes = quote.get('volume') or []

    out = []
    for i, ts in enumerate(timestamps):
        close = closes[i] if i < len(closes) else None
        if close is None:
            continue
        date_str = dt.datetime.utcfromtimestamp(ts).strftime('%Y%m%d')
        out.append({
            'date': date_str,
            'open': opens[i] if i < len(opens) else None,
            'high': highs[i] if i < len(highs) else None,
            'low': lows[i] if i < len(lows) else None,
            'close': close,
            'volume': volumes[i] if i < len(volumes) else None,
        })
    return out


def fetch_current_quote(symbol: str) -> dict | None:
    """실시간에 가까운 현재가·거래량. 실패·결손이면 None(측정 불가)."""
    try:
        res = _get_chart(symbol, '1d')
    except Exception:
        return None
    meta = res.get('meta') or {}
    price = meta.get('regularMarketPrice')
    if price is None:
        return None
    return {'price': float(price), 'volume': float(meta.get('regularMarketVolume') or 0)}
