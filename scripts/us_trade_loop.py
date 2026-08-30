"""US Sim1(이후 US 심 전체) 장중 페이퍼 체결 루프.

발화는 태스커가 한다. trading.yml이 09:00~06:00 KST 2분 트리거를 받아
세션을 가르고(src/session_gate.py), 미국장이면 us_trading.yml을 dispatch한다.

예전에는 "US 심은 페이퍼라 네이티브 cron으로 충분하다"고 봤는데 그게 틀렸다.
2026-08-27부터 `*/5 13-21` cron 발화 자체가 드롭됐고(18 → 1 → 0건/일), 남은
런마저 폐장 뒤라 즉시 종료해 목·금 세션 거래가 0건이었다. 실패가 아니라
미발화라 Actions는 내내 초록이었다. cron은 이제 30분 간격 백업으로만 남는다.

    PYTHONPATH=. python scripts/us_trade_loop.py
"""
import datetime as dt
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src import alerts  # noqa: E402
from src.data.us_ohlcv import fetch_current_quote  # noqa: E402
from src.session_gate import us_session_open as is_us_market_open  # noqa: E402,F401
from src.strategy.us_registry import get_active_us_simulators  # noqa: E402

# 판정은 src/session_gate.py 하나에 있다. 라우팅 스텝(trading.yml)이 pip install
# 앞에서 같은 판정을 해야 하는데, 이 모듈은 requests·yfinance를 끌고 온다.


def run_cycle(simulators, fetch_quote) -> dict[str, int]:
    """감시목록 + 보유종목 심볼만 조회해 각 심을 한 바퀴 돌린다.

    반환: 심 이름 → 실제로 넘긴 후보 수. 호출부가 결손을 판정하는 데 쓴다."""
    counts = {}
    for sim in simulators:
        candidates_raw = sim.get_universe() or []
        symbols = {c['code'] for c in candidates_raw if c.get('code')}
        symbols |= set(sim.state.get('portfolio', {}).keys())

        quotes = {}
        for code in symbols:
            q = fetch_quote(code)
            if q is not None:
                quotes[code] = q

        current_prices = {code: q['price'] for code, q in quotes.items()}
        candidates = []
        for c in candidates_raw:
            code = c.get('code')
            q = quotes.get(code)
            if q is None:
                continue
            entry = dict(c)
            entry['price'] = q['price']
            entry['amount'] = q['price'] * q['volume']
            candidates.append(entry)

        sim.run(candidates, current_prices)
        counts[sim.name] = len(candidates)
    return counts


# 루프는 장중 5분마다 돈다(세션당 78회). 억제가 없으면 결손 하루에 78건이 울려
# 텔레그램 유량에 걸리거나 사람이 둔감해진다 — 어느 쪽이든 침묵과 같다.
# 60분이면 세션당 6~7번으로, 무시하기는 어렵고 도배도 아니다(alerts.py의
# 휴장 판정 실패 알림과 같은 관례).
WATCHLIST_ALERT_COOLDOWN_MIN = 60


def main():
    if not is_us_market_open():
        print('[US-Loop] 미국장 시간이 아님 — 종료')
        return
    simulators = get_active_us_simulators()
    counts = run_cycle(simulators, fetch_current_quote)
    detail = ', '.join(f'{name} 후보 {n}' for name, n in counts.items())
    print(f'[US-Loop] {len(simulators)}개 심 실행 완료 — {detail}')

    # 후보 0개와 "오늘은 살 게 없다"는 로그에서 똑같이 생겼다. 둘을 가르는 건
    # **전 심이 동시에 0인가**다. EOD 배치가 돌았다면 심마다 판정이 다르므로
    # 전부 0이 되기는 어렵다 — 전부 0이면 워치리스트 자체가 없다고 본다.
    # (2026-08-26: 배치가 이틀 죽어 있는 동안 이 루프가 계속 초록이었다.)
    if counts and not any(counts.values()):
        alerts.send_alert_once(
            'us_watchlist_empty',
            '<b>US 워치리스트 결손</b>\n\n'
            f'전 심의 후보가 0개입니다 — {", ".join(counts)}.\n'
            'EOD 배치(us_eod_watchlist.yml)가 실패했을 가능성이 높습니다. '
            '워치리스트가 없으면 미국 심은 한 건도 매매하지 않습니다.',
            dt.datetime.now(dt.timezone.utc),
            cooldown_min=WATCHLIST_ALERT_COOLDOWN_MIN)


if __name__ == '__main__':
    main()
