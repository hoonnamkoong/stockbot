"""US Sim1 EOD 워치리스트 배치 — 하루 1회, 미국장 마감 이후 실행.

무거운 계산(추세 템플릿·VCP 압축·실적 가속)을 여기서 끝내고
data/sim_us1_minervini_watchlist.json에 남긴다. 장중 루프(us_trade_loop.py)는
이 파일만 읽고 실시간가로 pivot 돌파만 본다(program-trading-parity 원칙).

트렌드 템플릿을 먼저 통과한 종목에만 SEC EDGAR를 조회한다 — 유니버스 전체에
펀더멘털을 조회하면 EDGAR 콜이 수백~수천 건이 된다.

    PYTHONPATH=. python scripts/run_eod_sim_us.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.us_universe import fetch_us_universe, filter_universe, save_universe  # noqa: E402
from src.data.us_ohlcv import fetch_daily_ohlcv  # noqa: E402
from src.data.us_fundamentals import fetch_cik_map, fetch_eps_revenue_growth  # noqa: E402
from src.strategy.simulators.us_sim1_minervini import (  # noqa: E402
    build_watchlist_entry, save_watchlist, _trend_template_ok,
)
from src.strategy.simulators.base_simulator import get_kst_now  # noqa: E402

MIN_HISTORY_DAYS = 220

# fetch_fundamentals(SEC EDGAR) 한 콜이 내부적으로 최대 4개 HTTP 요청을 낸다.
# SEC 정책상 10 req/s 이하를 지켜야 하므로, 트렌드 템플릿을 통과해 실제로
# EDGAR를 호출하는 종목마다 호출 직후 슬립을 준다.
FUNDAMENTALS_RATE_LIMIT_SLEEP_SEC = 0.15


def build_watchlist_for_universe(universe, cik_map, fetch_ohlcv, fetch_fundamentals):
    """오케스트레이션. 네트워크 함수는 주입 — 테스트에서 모킹한다."""
    out = {}
    for row in universe:
        symbol = row['symbol']
        bars = fetch_ohlcv(symbol)
        if len(bars) < MIN_HISTORY_DAYS:
            continue
        closes = [b['close'] for b in bars]
        price = closes[-1]
        daily_closes = closes[:-1]
        w52_window = bars[-252:] if len(bars) >= 252 else bars
        w52_hgpr = max(b['high'] for b in w52_window)
        w52_lwpr = min(b['low'] for b in w52_window)

        if not _trend_template_ok(price, daily_closes, w52_hgpr, w52_lwpr):
            continue

        cik = cik_map.get(symbol)
        if not cik:
            continue
        fund = fetch_fundamentals(cik)
        time.sleep(FUNDAMENTALS_RATE_LIMIT_SLEEP_SEC)

        entry = build_watchlist_entry({
            'symbol': symbol, 'name': row.get('name', symbol), 'price': price,
            'daily_closes': daily_closes, 'w52_hgpr': w52_hgpr, 'w52_lwpr': w52_lwpr,
            'eps_growth_yoy': fund.get('eps_growth_yoy'),
            'revenue_growth_yoy': fund.get('revenue_growth_yoy'),
        })
        if entry:
            out[symbol] = entry
    return out


def main():
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    universe_raw = fetch_us_universe(limit=1000)
    universe = filter_universe(universe_raw)
    save_universe(universe, os.path.join(data_dir, 'us_universe.json'))
    print(f'[EOD-US] 유니버스 {len(universe)}종목')

    cik_map = fetch_cik_map()
    watchlist = build_watchlist_for_universe(
        universe, cik_map, fetch_daily_ohlcv, fetch_eps_revenue_growth)
    today = get_kst_now().strftime('%Y%m%d')
    save_watchlist(watchlist, today)
    print(f'[EOD-US] 워치리스트 {len(watchlist)}종목 저장 (날짜 {today})')


if __name__ == '__main__':
    main()
