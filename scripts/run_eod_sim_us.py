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

from src import alerts  # noqa: E402
from src.data.us_universe import (  # noqa: E402
    fetch_us_universe, filter_universe, load_universe, save_universe)
from src.data.us_ohlcv import fetch_daily_ohlcv  # noqa: E402
from src.data.us_fundamentals import fetch_cik_map, fetch_eps_revenue_growth  # noqa: E402
from src.strategy.simulators.us_calendar import watchlist_target_date  # noqa: E402
from src.strategy.simulators.us_sim1_minervini import (  # noqa: E402
    build_watchlist_entry as build_sim1_entry,
    save_watchlist as save_sim1_watchlist,
    _trend_template_ok,
)
from src.strategy.simulators.us_sim2_donchian import (  # noqa: E402
    build_watchlist_entry as build_sim2_entry,
    cap_watchlist as cap_sim2_watchlist,
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
    # US Sim2는 셋업 판정을 통과한 종목이 수백 개가 된다(2026-08-26 실측 930).
    # 장중 루프의 호출 예산에 맞춰 거래대금 상위만 남긴다 — 판정 뒤에 자른다.
    capped2 = cap_sim2_watchlist(out2)
    if len(capped2) < len(out2):
        print(f'[EOD-US] US Sim2 워치리스트 {len(out2)}→{len(capped2)}종목 (거래대금 상위 상한)')
    return out1, capped2, build_sim3_watchlist(liquidity_rows)


def main():
    # 이 배치가 죽으면 다음 거래일 미국 심은 통째로 0건이 된다. 예외는 알린 뒤
    # 그대로 올린다 — 삼키면 잡이 초록으로 끝나 실패가 두 겹으로 묻힌다.
    # (2026-08-26: 08-24·08-25 두 번 다 유니버스 조회에서 죽었는데 이틀 동안
    #  아무도 몰랐다. 빨간 X가 Actions 로그에만 남았기 때문이다.)
    try:
        _run()
    except Exception as e:
        alerts.send_alert(
            '<b>US EOD 워치리스트 배치 실패</b>\n\n'
            f'{type(e).__name__}: {e}\n\n'
            '다음 거래일 미국 심은 한 건도 매매하지 않습니다.')
        raise


def resolve_universe(path: str) -> tuple[list[dict], bool]:
    """(유니버스, 직전 것을 쓴 건가).

    스크리너가 죽어도 워치리스트는 만든다. 2026-08-24·25에 나스닥 소프트 차단으로
    이 배치가 예외로 죽었고 미국 심 3개가 그 세션을 워치리스트 없이 보냈다 —
    매매도 손절도 0건이다.

    유니버스는 **상장 종목 목록**이라 하루 이틀 낡아도 거의 안 변한다. 워치리스트가
    아예 없는 것보다 낫다. 다만 조용히 넘어가지 않는다 — 알림을 보내고, 파일 자체는
    config/data_freshness.yaml의 data/us_universe.json 항목이 계속 지적한다.
    """
    try:
        return filter_universe(fetch_us_universe(limit=1000)), False
    except Exception as e:
        prev = load_universe(path)
        if not prev:
            # 빈 유니버스로 "정상 종료"하면 워치리스트 0종목이 정상처럼 보인다.
            raise RuntimeError(
                f'유니버스 조회 실패({type(e).__name__}: {e})이고 직전 유니버스도 '
                '없다 — 워치리스트를 만들 수 없다.') from e
        alerts.send_alert(
            '<b>US 유니버스 조회 실패 — 직전 것으로 진행</b>\n\n'
            f'{type(e).__name__}: {e}\n\n'
            f'직전 유니버스 {len(prev)}종목으로 워치리스트를 만듭니다. '
            '종목 목록은 하루 이틀 낡아도 거의 안 변하지만, 계속되면 '
            '신규 상장·상폐가 반영되지 않습니다.')
        return prev, True


def _run():
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    universe_path = os.path.join(data_dir, 'us_universe.json')
    universe, stale = resolve_universe(universe_path)
    if not stale:
        # 폴백일 때는 저장하지 않는다 — 같은 내용을 다시 쓰면 커밋 시각이 갱신돼
        # 신선도 감사가 "방금 갱신됨"으로 속는다.
        save_universe(universe, universe_path)
    print(f'[EOD-US] 유니버스 {len(universe)}종목'
          + (' (직전 것 재사용)' if stale else ''))

    cik_map = fetch_cik_map()
    watchlist1, watchlist2, watchlist3 = build_watchlists_for_universe(
        universe, cik_map, fetch_daily_ohlcv, fetch_eps_revenue_growth)
    # 아직 안 끝난 가장 가까운 세션 — 장중에 돌리면 오늘치로 찍혀 그 자리에서
    # 쓰인다. 마감 뒤 정규 배치(22:00 UTC)는 지금까지처럼 다음 거래일이다.
    today = watchlist_target_date()
    save_sim1_watchlist(watchlist1, today)
    save_sim2_watchlist(watchlist2, today)
    save_sim3_watchlist(watchlist3, today)
    print(f'[EOD-US] US Sim1 워치리스트 {len(watchlist1)}종목, '
          f'US Sim2 워치리스트 {len(watchlist2)}종목, '
          f'US Sim3 워치리스트 {len(watchlist3)}종목 저장 (날짜 {today})')

    # 예외 없이 끝나도 셋이 전부 비면 결과는 배치가 죽은 것과 같다. 심마다 판정이
    # 다른데 동시에 0이 되는 건 정상 결과가 아니라 입력 쪽 고장에 가깝다
    # (US Sim3는 판정이 없어 유니버스만 살아 있으면 늘 채워진다).
    if not (watchlist1 or watchlist2 or watchlist3):
        alerts.send_alert(
            '<b>US 워치리스트가 전부 비었습니다</b>\n\n'
            f'유니버스 {len(universe)}종목을 훑었으나 세 심 모두 0종목입니다 (날짜 {today}).\n'
            '야후 OHLCV 또는 SEC EDGAR 조회를 확인하세요.')


if __name__ == '__main__':
    main()
