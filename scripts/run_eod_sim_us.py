"""US 심 EOD 워치리스트 배치 — 하루 1회, 미국장 마감 이후 실행.

무거운 계산(US Sim1: 추세 템플릿·VCP 압축·실적 가속, US Sim2: 채널 상단/하단·ATR)을
여기서 끝내고 심마다 자기 워치리스트 파일에 남긴다. 장중 루프(us_trade_loop.py)는
그 파일만 읽고 실시간가로 진입/청산 문턱만 본다(program-trading-parity 원칙).

야후 OHLCV는 종목당 한 번만 받아 두 심 판정에 같이 쓴다(호출을 두 배로 늘리지
않는다). 두 판정은 서로 독립이다 — US Sim1이 탈락해도 US Sim2는 별도로 평가한다.
SEC EDGAR는 US Sim1의 추세 템플릿을 통과한 종목에만 조회한다(유니버스 전체에
펀더멘털을 조회하면 EDGAR 콜이 수백~수천 건이 된다). US Sim2는 펀더멘털이 필요
없다 — 대신 EOD 시점의 평균거래대금으로 후보를 미리 좁힌다(모듈 docstring 참고,
장중 루프가 워치리스트 전 종목을 매 사이클 실시간 조회하므로 워치리스트가 커지면
타임아웃·야후 차단 리스크가 생긴다).

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
    build_watchlist_entry as build_sim1_entry,
    save_watchlist as save_sim1_watchlist,
    next_us_trading_date, _trend_template_ok,
)
from src.strategy.simulators.us_sim2_donchian import (  # noqa: E402
    build_watchlist_entry as build_sim2_entry,
    save_watchlist as save_sim2_watchlist,
    CHANNEL_DAYS as SIM2_CHANNEL_DAYS,
)
from src.strategy.simulators.us_sim3_liquidity import (  # noqa: E402
    build_watchlist as build_sim3_watchlist,
    save_watchlist as save_sim3_watchlist,
)

MIN_HISTORY_DAYS = 220

# fetch_fundamentals(SEC EDGAR) 한 콜이 내부적으로 최대 4개 HTTP 요청을 낸다.
# SEC 정책상 10 req/s 이하를 지켜야 하므로, 트렌드 템플릿을 통과해 실제로
# EDGAR를 호출하는 종목마다 호출 직후 슬립을 준다.
FUNDAMENTALS_RATE_LIMIT_SLEEP_SEC = 0.15

# 야후 비공식 API는 지속적인 고속 요청에 429로 소프트 차단을 건다.
# 유니버스 전체(최대 1000종목)를 무지연으로 때리지 않도록 종목마다 슬립을 준다.
YAHOO_RATE_LIMIT_SLEEP_SEC = 0.15


def build_watchlists_for_universe(universe, cik_map, fetch_ohlcv, fetch_fundamentals):
    """오케스트레이션. 네트워크 함수는 주입 — 테스트에서 모킹한다.

    반환: (sim1_watchlist, sim2_watchlist, sim3_watchlist). 세 판정은 서로 독립이라
    한쪽이 탈락해도 다른 쪽은 계속 평가한다.

    US Sim3(기준선)은 판정이 없다 — 여기서 모은 (심볼, 이름, 평균거래대금)을
    그대로 정렬해 상위 N을 뽑을 뿐이다. 그래서 추가 네트워크 호출이 0이다."""
    out1 = {}
    out2 = {}
    liquidity_rows = []
    failures = 0
    for row in universe:
        symbol = row['symbol']
        # 상장폐지·신규상장·티커 표기 불일치는 1000종목 규모에선 늘 몇 건 나온다.
        # 한 종목의 조회 실패가 배치 전체를 죽이면 그날 워치리스트가 통째로 빈다.
        try:
            bars = fetch_ohlcv(symbol)
        except Exception:
            failures += 1
            bars = None
        time.sleep(YAHOO_RATE_LIMIT_SLEEP_SEC)
        if bars is None or len(bars) < MIN_HISTORY_DAYS:
            continue
        closes = [b['close'] for b in bars]
        price = closes[-1]
        daily_closes = closes[:-1]
        w52_window = bars[-252:] if len(bars) >= 252 else bars
        w52_hgpr = max(b['high'] for b in w52_window)
        w52_lwpr = min(b['low'] for b in w52_window)
        name = row.get('name', symbol)

        # 두 심이 공유하는 평균거래대금(최근 SIM2_CHANNEL_DAYS일, 종가×거래량 평균).
        # 장중 루프의 실시간 amount(당일 누적 거래량×가격)는 개장 직후 몇 시간은
        # 실제 유동성과 무관하게 작게 나온다 — 여기서 계산한 EOD 값을 흐름·청산
        # 게이트의 유동성 문턱으로 쓰고, 실시간 amount는 거래대금 급증(z-score)
        # 판정에만 남긴다.
        volumes = [b.get('volume') or 0 for b in bars[:-1]]
        recent_dollar = [c * v for c, v in zip(daily_closes[-SIM2_CHANNEL_DAYS:],
                                                volumes[-SIM2_CHANNEL_DAYS:])]
        avg_dollar_volume = sum(recent_dollar) / len(recent_dollar) if recent_dollar else 0.0

        # US Sim3(기준선) — 판정 없이 전 종목을 모아 두고, 아래에서 상위 N만 남긴다.
        liquidity_rows.append((symbol, name, avg_dollar_volume))

        # US Sim1 — 추세 템플릿 통과 종목만 EDGAR 조회.
        if _trend_template_ok(price, daily_closes, w52_hgpr, w52_lwpr):
            cik = cik_map.get(symbol)
            if cik:
                fund = fetch_fundamentals(cik)
                time.sleep(FUNDAMENTALS_RATE_LIMIT_SLEEP_SEC)
                entry1 = build_sim1_entry({
                    'symbol': symbol, 'name': name, 'price': price,
                    'daily_closes': daily_closes, 'w52_hgpr': w52_hgpr, 'w52_lwpr': w52_lwpr,
                    'eps_growth_yoy': fund.get('eps_growth_yoy'),
                    'revenue_growth_yoy': fund.get('revenue_growth_yoy'),
                    'avg_dollar_volume': avg_dollar_volume,
                })
                if entry1:
                    out1[symbol] = entry1

        # US Sim2 — 펀더멘털 불필요. 위에서 이미 계산한 평균거래대금으로 후보를 좁힌다.
        entry2 = build_sim2_entry(name, daily_closes, avg_dollar_volume)
        if entry2:
            out2[symbol] = entry2
    if failures:
        print(f'[EOD-US] 종목 조회 실패 {failures}건 (건너뜀)')
    return out1, out2, build_sim3_watchlist(liquidity_rows)


def main():
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    universe_raw = fetch_us_universe(limit=1000)
    universe = filter_universe(universe_raw)
    save_universe(universe, os.path.join(data_dir, 'us_universe.json'))
    print(f'[EOD-US] 유니버스 {len(universe)}종목')

    cik_map = fetch_cik_map()
    watchlist1, watchlist2, watchlist3 = build_watchlists_for_universe(
        universe, cik_map, fetch_daily_ohlcv, fetch_eps_revenue_growth)
    today = next_us_trading_date()
    save_sim1_watchlist(watchlist1, today)
    save_sim2_watchlist(watchlist2, today)
    save_sim3_watchlist(watchlist3, today)
    print(f'[EOD-US] US Sim1 워치리스트 {len(watchlist1)}종목, '
          f'US Sim2 워치리스트 {len(watchlist2)}종목, '
          f'US Sim3 워치리스트 {len(watchlist3)}종목 저장 (날짜 {today})')


if __name__ == '__main__':
    main()
