import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.pipeline.us_brief import (  # noqa: E402
    build_us_brief, collect_us_sim_brief, overnight_window, _profit_rate_from_state)

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


def test_overnight_window_midweek_starts_yesterday_2200():
    """화~금은 전일 22:00 ~ 당일 09:00 그대로다."""
    since, until = overnight_window(NOW)  # 2026-09-01 화요일
    assert since == '2026-08-31 22:00'
    assert until == '2026-09-01 09:00'


def test_overnight_window_on_monday_reaches_back_to_friday():
    """월요일 창은 **금요일 22:00**에서 시작한다.

    전일(일요일) 22:00으로 잡으면 창에 미국 세션이 하나도 없어 세 심 모두
    '0종목'을 찍는다 — '거래가 없었다'가 아니라 '세션이 없었다'인데 같은 0으로
    뭉개진다. 그리고 금요일 밤 세션은 토요일에 런이 없어(kr_session_open=False)
    매주 통째로 유실된다. 이 테스트는 그 두 결함을 동시에 잡는다.
    """
    monday = datetime(2026, 9, 7, 9, 5)
    assert monday.weekday() == 0
    since, until = overnight_window(monday)
    assert since == '2026-09-04 22:00'   # 금요일
    assert until == '2026-09-07 09:00'


def test_overnight_window_counts_the_friday_night_session_on_monday():
    """금요일 밤 22:31 체결이 월요일 창 안에 들어온다(문자열 비교 기준)."""
    since, until = overnight_window(datetime(2026, 9, 7, 9, 5))
    assert since <= '2026-09-04 22:31:41' < until


def test_body_states_the_covered_window():
    """0종목이 해석 가능하려면 어느 구간을 셌는지 본문에 있어야 한다.

    미국 공휴일 달력이 이 레포에 없어 휴장일에는 여전히 0종목이 찍힌다.
    구간을 함께 찍는 것이 없는 달력을 지어내지 않는 정직한 대안이다.
    """
    msg = build_us_brief(OK_SIMS, NOW)
    assert '2026-08-31 22:00' in msg
    assert '2026-09-01 09:00' in msg


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


def test_profit_rate_from_state_returns_none_when_file_not_found(tmp_path):
    """파일이 없으면 None을 반환한다. 절대 0이 아니다."""
    path = str(tmp_path / 'nonexistent.json')
    result = _profit_rate_from_state(path)
    assert result is None


def test_profit_rate_from_state_returns_none_on_invalid_json(tmp_path):
    """유효하지 않은 JSON이면 None을 반환한다. 절대 0이 아니다."""
    state_file = tmp_path / 'state.json'
    state_file.write_text('{ invalid json }', encoding='utf-8')
    result = _profit_rate_from_state(str(state_file))
    assert result is None


def test_profit_rate_from_state_returns_none_when_initial_cash_missing(tmp_path):
    """initial_cash가 없으면 None을 반환한다. 절대 0이 아니다."""
    state_file = tmp_path / 'state.json'
    state_file.write_text('{"cash": 10000, "portfolio": {}}', encoding='utf-8')
    result = _profit_rate_from_state(str(state_file))
    assert result is None


def test_profit_rate_from_state_returns_none_when_initial_cash_zero(tmp_path):
    """initial_cash가 0이면 None을 반환한다. 절대 0이 아니다."""
    state_file = tmp_path / 'state.json'
    state_file.write_text('{"initial_cash": 0, "cash": 10000, "portfolio": {}}', encoding='utf-8')
    result = _profit_rate_from_state(str(state_file))
    assert result is None


def test_profit_rate_from_state_returns_none_when_initial_cash_negative(tmp_path):
    """initial_cash가 음수면 None을 반환한다. 절대 0이 아니다."""
    state_file = tmp_path / 'state.json'
    state_file.write_text('{"initial_cash": -1000, "cash": 10000, "portfolio": {}}', encoding='utf-8')
    result = _profit_rate_from_state(str(state_file))
    assert result is None


def test_collect_us_sim_brief_returns_none_on_missing_state_file(tmp_path):
    """상태 파일이 없으면 collect_us_sim_brief가 None을 반환한다. 절대 0이 아니다."""
    # 거래 이력만 만들고 상태 파일은 없음
    (tmp_path / 'trade_history_sim_us2donchian.csv').write_text(
        'timestamp,symbol\n'
        '2026-08-31 22:31:41,AAPL\n',
        encoding='utf-8')

    sims = collect_us_sim_brief(str(tmp_path), NOW)
    row = next(s for s in sims if 'US Sim 2' in s['label'])
    assert row['profit_rate'] is None


# ── 09:00 슬롯 게이트 ────────────────────────────────────────────────

def test_us_slot_does_not_touch_the_kr_gate_state(tmp_path):
    """writer가 하나여야 한다. 미국 브리핑이 국내 상태 파일을 건드리면
    scraper.yml이 방금 닫은 슬롯이 다시 열린다."""
    from src.report import gate
    now = datetime(2026, 9, 1, 9, 5)

    assert gate.us_brief_due(now, str(tmp_path)) is True
    gate.mark_sent(gate.US_BRIEF_SLOT, now, str(tmp_path),
                   filename=gate.US_BRIEF_STATE_FILENAME)

    assert gate.us_brief_due(now, str(tmp_path)) is False
    assert not (tmp_path / gate.STATE_FILENAME).exists()
    # 국내 브리핑 판정은 영향을 받지 않는다
    assert gate.brief_due(datetime(2026, 9, 1, 12, 5), str(tmp_path)) == '12:00'


def test_us_slot_window_is_40_minutes(tmp_path):
    """창은 국내 슬롯과 같은 40분이다. 09:41은 이미 늦은 브리핑이다."""
    from src.report import gate
    assert gate.us_brief_due(datetime(2026, 9, 1, 9, 39), str(tmp_path)) is True
    assert gate.us_brief_due(datetime(2026, 9, 1, 9, 41), str(tmp_path)) is False
    assert gate.us_brief_due(datetime(2026, 9, 1, 8, 59), str(tmp_path)) is False
