"""US Sim1(이후 US 심 전체) 장중 페이퍼 체결 루프.

국내(trading.yml)는 태스커가 2분마다 repository_dispatch로 깨우는데, 그건
GitHub Actions 네이티브 cron이 부하 시 밀리는 지연이 **실손실**로 이어지기
때문이다. US 심은 페이퍼(자본 이동 없음)라 그 제약이 없다 — 네이티브 cron +
zoneinfo 게이트로 충분하고, 사용자 폰(태스커)이 한국시간 밤새 깨어 있을 필요가
없다.

    PYTHONPATH=. python scripts/us_trade_loop.py
"""
import datetime as dt
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.data.us_ohlcv import fetch_current_quote  # noqa: E402
from src.strategy.us_registry import get_active_us_simulators  # noqa: E402

_NY = ZoneInfo('America/New_York')


def is_us_market_open(now_utc: dt.datetime | None = None) -> bool:
    """평일 09:30~16:00 ET. zoneinfo가 서머타임을 자동 반영한다."""
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local = now_utc.astimezone(_NY)
    if local.weekday() >= 5:  # 토(5)·일(6)
        return False
    open_t = local.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = local.replace(hour=16, minute=0, second=0, microsecond=0)
    return open_t <= local < close_t


def run_cycle(simulators, fetch_quote) -> None:
    """감시목록 + 보유종목 심볼만 조회해 각 심을 한 바퀴 돌린다."""
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


def main():
    if not is_us_market_open():
        print('[US-Loop] 미국장 시간이 아님 — 종료')
        return
    simulators = get_active_us_simulators()
    run_cycle(simulators, fetch_current_quote)
    print(f'[US-Loop] {len(simulators)}개 심 실행 완료')


if __name__ == '__main__':
    main()
