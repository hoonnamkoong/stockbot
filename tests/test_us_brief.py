import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.us_brief import (  # noqa: E402
    build_us_brief, collect_us_sim_brief, overnight_window)

NOW = datetime(2026, 9, 1, 9, 5)
OK_SIMS = [
    {'label': 'US 미너비니 추세형 (US Sim 1)', 'profit_rate': 3.21, 'ticker_count': 2},
    {'label': 'US 돈치안 돌파 (US Sim 2)', 'profit_rate': -1.5, 'ticker_count': 4},
    {'label': 'US 기준선·유동성 상위 (US Sim 3)', 'profit_rate': None, 'ticker_count': 0},
]


def test_title_names_the_us_close():
    msg = build_us_brief(OK_SIMS, NOW)
    assert '미국장 마감 브리핑' in msg
    assert '09/01' in msg


def test_unknown_profit_rate_is_not_zero():
    """조회 실패는 '측정 불가'다. 0%는 '정상적으로 본전'이라는 뜻이라 다르다."""
    msg = build_us_brief(OK_SIMS, NOW)
    assert '측정 불가' in msg
    assert '+0.00%' not in msg


def test_signs_are_explicit():
    msg = build_us_brief(OK_SIMS, NOW)
    assert '+3.21%' in msg
    assert '-1.50%' in msg


def test_no_real_account_block():
    """미국 심은 전부 페이퍼다. 실계좌 블록이 있으면 안 된다."""
    msg = build_us_brief(OK_SIMS, NOW)
    assert '실전 계좌' not in msg
    assert '예수금' not in msg


def test_overnight_window_is_prev_2200_to_today_0900():
    since, until = overnight_window(NOW)
    assert since == '2026-08-31 22:00'
    assert until == '2026-09-01 09:00'


def test_collect_counts_only_the_overnight_window(tmp_path):
    (tmp_path / 'sim_us2donchian_state.json').write_text(
        '{"initial_cash": 10000, "cash": 10000, "portfolio": {}}', encoding='utf-8')
    (tmp_path / 'trade_history_sim_us2donchian.csv').write_text(
        'timestamp,symbol\n'
        '2026-08-31 22:31:41,AAPL\n'      # 간밤 — 센다
        '2026-09-01 05:00:00,MSFT\n'      # 간밤 — 센다
        '2026-08-31 15:00:00,TSLA\n',     # 창 밖 — 안 센다
        encoding='utf-8')

    sims = collect_us_sim_brief(str(tmp_path), NOW)
    row = next(s for s in sims if 'US Sim 2' in s['label'])
    assert row['ticker_count'] == 2
