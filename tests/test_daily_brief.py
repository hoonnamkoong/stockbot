import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.trade.balance import _parse_holding


def test_parse_holding_includes_pl_amount():
    item = {
        'pdno': '005930', 'prdt_name': '삼성전자', 'hldg_qty': '10',
        'pchs_avg_pric': '70000', 'prpr': '75000',
        'evlu_pfls_rt': '7.14', 'evlu_pfls_amt': '50000',
    }
    h = _parse_holding(item)
    assert h['code'] == '005930'
    assert h['qty'] == 10
    assert h['current_price'] == 75000
    assert h['pl_amount'] == 50000


def test_parse_holding_missing_pl_amount_is_zero():
    item = {'pdno': '005930', 'prdt_name': '삼성전자', 'hldg_qty': '10',
            'pchs_avg_pric': '70000', 'prpr': '75000', 'evlu_pfls_rt': '0'}
    assert _parse_holding(item)['pl_amount'] == 0


from datetime import datetime
from src.pipeline.daily_brief import build_daily_brief

NOW = datetime(2026, 7, 22, 15, 0)

OK_BALANCE = {
    'deposit': 1_240_000,
    'holdings': [
        {'code': 'A', 'qty': 10, 'current_price': 300_000, 'pl_amount': 150_000},
        {'code': 'B', 'qty': 5,  'current_price': 450_000, 'pl_amount': 100_000},
    ],
}
OK_SIMS = [
    {'label': '심리 괴리형 (Sim 1)', 'profit_rate': -1.11, 'ticker_count': 6},
    {'label': '가치 페어형 (Sim 3)', 'profit_rate': 0.0, 'ticker_count': 0},
]


def test_brief_has_header_and_account_numbers():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, NOW, '15:00')
    assert '07/22 (수)' in msg
    assert '1,240,000원' in msg          # 예수금
    assert '5,250,000원' in msg          # 보유총액 = 10*300000 + 5*450000
    assert '+250,000원' in msg           # 평가손익 = 150000 + 100000
    assert '+5.00%' in msg               # 250000 / (5250000-250000)


def test_brief_lists_every_sim_with_rate_and_count():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, NOW, '15:00')
    assert '심리 괴리형 (Sim 1)' in msg
    assert '-1.11%' in msg
    assert '6종목' in msg
    assert '가치 페어형 (Sim 3)' in msg
    assert '+0.00%' in msg
    assert '0종목' in msg


def test_brief_reports_balance_error_without_dropping_sims():
    msg = build_daily_brief({'error': 'KIS API 오류: 토큰 만료', 'holdings': []}, OK_SIMS, NOW, '15:00')
    assert '조회 실패' in msg
    assert 'KIS API 오류: 토큰 만료' in msg
    assert '1,240,000원' not in msg
    assert '심리 괴리형 (Sim 1)' in msg   # 심 블록은 살아있어야 한다


def test_brief_no_holdings_shows_dash_not_zero_percent():
    """분모(매입원가)가 0이면 수익률은 0%가 아니라 모르는 값이다."""
    msg = build_daily_brief({'deposit': 3_000_000, 'holdings': []}, OK_SIMS, NOW, '15:00')
    assert '3,000,000원' in msg
    assert '—' in msg
    assert '0.00%' not in msg.split('🤖')[0]   # 계좌 블록 한정


def test_brief_sim_without_raw_stats_marked_unmeasurable():
    sims = [{'label': '하락 줍줍형 (Sim 6)', 'profit_rate': None, 'ticker_count': 0}]
    msg = build_daily_brief(OK_BALANCE, sims, NOW, '15:00')
    assert '측정 불가' in msg
    assert '하락 줍줍형 (Sim 6)' in msg


import json
from src.pipeline.daily_brief import collect_sim_brief, SIM_BRIEF_TARGETS


def test_targets_cover_trading_sims():
    """개수를 박아두지 않는다 — 심을 추가할 때 이 테스트가 오히려 누락을 고정한다.

    매니페스트와의 실제 대조는 tests/test_sim_registry_consistency.py가 한다.
    여기서는 형식과 분석기 제외만 본다.
    """
    states = [t[1] for t in SIM_BRIEF_TARGETS]
    assert len(states) == len(set(states)), '상태 파일 중복'
    assert 'sim_psych_state.json' in states
    assert 'sim_orchestrator_state.json' in states
    assert 'sim_libero_state.json' not in states   # 분석기는 제외


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding='utf-8')


def test_collect_reads_state_and_counts_distinct_tickers(tmp_path):
    # cash=2,967,000 / initial_cash=3,000,000, 포트폴리오 없음 → -1.1%
    _write(tmp_path, 'sim_psych_state.json',
           json.dumps({'cash': 2_967_000, 'initial_cash': 3_000_000, 'portfolio': {}}))
    _write(tmp_path, 'trade_history_sim_psych.csv',
           'timestamp,symbol,action,price,quantity,total_amount,reason\n'
           '2026-07-22 09:10:00,금호타이어(073240),BUY,6270,47,294690,x\n'
           '2026-07-22 14:10:00,금호타이어(073240),SELL,6400,47,300800,x\n'
           '2026-07-22 11:00:00,LG디스플레이(034220),BUY,10160,29,294640,x\n'
           '2026-07-21 11:00:00,대우건설(047040),BUY,14800,19,281200,x\n')

    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    psych = next(r for r in rows if 'Sim 1' in r['label'])
    assert abs(psych['profit_rate'] - (-1.1)) < 1e-9
    assert psych['ticker_count'] == 2   # 같은 종목 2회 = 1종목, 어제 건은 제외


def test_collect_missing_files_are_unmeasurable_not_zero(tmp_path):
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    assert len(rows) == len(SIM_BRIEF_TARGETS)
    assert all(r['profit_rate'] is None for r in rows)   # 상태 없음 = 모름
    assert all(r['ticker_count'] == 0 for r in rows)     # CSV 없음 = 거래 없음


def test_collect_state_without_initial_cash_is_unmeasurable(tmp_path):
    """initial_cash가 없으면 분모를 만들 수 없어 여전히 None (raw_stats 유무는 무관)."""
    _write(tmp_path, 'sim_bear_state.json', json.dumps({'cash': 3000000}))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    bear = next(r for r in rows if 'Sim 6' in r['label'])
    assert bear['profit_rate'] is None


def test_collect_state_with_zero_initial_cash_is_unmeasurable(tmp_path):
    _write(tmp_path, 'sim_bear_state.json',
           json.dumps({'cash': 0, 'initial_cash': 0, 'portfolio': {}}))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    bear = next(r for r in rows if 'Sim 6' in r['label'])
    assert bear['profit_rate'] is None


def test_collect_uses_state_initial_cash_as_denominator(tmp_path):
    """버그 본체: 리셋으로 initial_cash가 5,000,000이 되면 분모도 5,000,000이어야 한다
    (파이썬 calculate_stats가 생성자 기본값 3,000,000을 계속 쓰던 버그의 회귀 테스트)."""
    _write(tmp_path, 'sim_bull_state.json',
           json.dumps({'cash': 4_500_000, 'initial_cash': 5_000_000, 'portfolio': {}}))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    bull = next(r for r in rows if 'Sim 4)' in r['label'])
    # (4,500,000 - 5,000,000) / 5,000,000 * 100 = -10.0%
    # 만약 분모가 옛 버그처럼 3,000,000으로 고정됐다면 -16.67%가 나온다.
    assert abs(bull['profit_rate'] - (-10.0)) < 1e-9


def test_collect_reset_state_is_zero_not_unmeasurable(tmp_path):
    """리셋 직후(raw_stats 없음, cash==initial_cash, 빈 포트폴리오)는 측정 불가가 아니라 0%."""
    _write(tmp_path, 'sim_risk_state.json',
           json.dumps({'cash': 3_000_000, 'initial_cash': 3_000_000, 'portfolio': {}}))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    risk = next(r for r in rows if 'Sim 3' in r['label'])
    assert risk['profit_rate'] == 0.0


def test_collect_ignores_raw_stats_profit_rate_uses_calculated_value(tmp_path):
    """상태 파일에 (옛 버그로 만든) raw_stats.profit_rate가 있어도 무시하고,
    cash/portfolio/initial_cash로 직접 계산한 값을 반환해야 한다.

    이 테스트가 없으면, 나중에 누군가 'raw_stats.profit_rate가 있으면 쓰고
    없으면 계산한다'는 절충 구현으로 되돌려도 현재 테스트는 전부 통과한다
    (raw_stats.profit_rate가 없기 때문). 그러면 원래 버그가 그대로 돌아온다."""
    # initial_cash=5,000,000, cash=5,500,000, 포트폴리오 없음
    # → 정상 계산: (5,500,000 - 5,000,000) / 5,000,000 * 100 = +10.0%
    # 하지만 raw_stats.profit_rate = 83.33 (옛 버그: 분모 3,000,000)
    # → (5,500,000 - 3,000,000) / 3,000,000 * 100 = 83.33
    _write(tmp_path, 'sim_spillover_state.json',
           json.dumps({
               'cash': 5_500_000,
               'initial_cash': 5_000_000,
               'portfolio': {},
               'raw_stats': {'profit_rate': 83.33, 'current_prices': {}}
           }))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    spillover = next(r for r in rows if 'Sim 2' in r['label'])
    # 10.0%가 나와야 함 (83.33 아님)
    assert abs(spillover['profit_rate'] - 10.0) < 1e-9


def test_corrupted_state_json_logs_error_and_returns_none(tmp_path, capsys):
    """손상된 JSON 파일(파싱 실패)이면 stdout에 로그를 남기고 profit_rate는 None."""
    _write(tmp_path, 'sim_psych_state.json', '{')  # 불완전한 JSON
    _write(tmp_path, 'trade_history_sim_psych.csv',
           'timestamp,symbol,action,price,quantity,total_amount,reason\n')

    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    psych = next(r for r in rows if 'Sim 1' in r['label'])

    # profit_rate은 여전히 None이어야 함 (반환값 계약 유지)
    assert psych['profit_rate'] is None

    # stdout에 [Brief] 접두로 오류 로그가 있어야 함
    captured = capsys.readouterr()
    assert '[Brief]' in captured.out
    assert 'sim_psych_state.json' in captured.out


def test_missing_state_json_silent_no_log(tmp_path, capsys):
    """파일이 없으면(FileNotFoundError) stdout에 아무 로그도 남기지 않음 (정상 상황)."""
    _write(tmp_path, 'trade_history_sim_psych.csv',
           'timestamp,symbol,action,price,quantity,total_amount,reason\n')

    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    psych = next(r for r in rows if 'Sim 1' in r['label'])

    # profit_rate은 None 반환
    assert psych['profit_rate'] is None

    # stdout에 로그가 없어야 함 (정상이므로)
    captured = capsys.readouterr()
    assert '[Brief]' not in captured.out


from src.pipeline.daily_brief import should_send_brief


def test_fifteen_slot_opens_for_forty_minutes(tmp_path):
    """15:00 슬롯은 15:00에 열려 40분간 재시도 창을 갖는다.

    (12:00 슬롯 자체는 tests/test_report_gate.py가 본다. 여기서는 마감 슬롯의
    경계만 고정한다 — 14:59에 열리면 안 되고 15:41엔 닫혀야 한다.)
    """
    from datetime import datetime
    d = str(tmp_path)

    assert should_send_brief(datetime(2026, 8, 10, 15, 0), d) == '15:00'
    assert should_send_brief(datetime(2026, 8, 10, 15, 30), d) == '15:00'
    assert should_send_brief(datetime(2026, 8, 10, 14, 59), d) is None
    assert should_send_brief(datetime(2026, 8, 10, 9, 1), d) is None
    assert should_send_brief(datetime(2026, 8, 10, 15, 41), d) is None


# --- 픽스 2: send_message 실패를 발송 완료로 기록하지 않는다 -----------------

import pytest
from src.pipeline.context import PipelineContext
from src.pipeline.workers.notifier import NotifierWorker


class _FakeTelegram:
    """실제 TelegramManager 대체용 최소 스텁. send_message 반환값만 통제한다."""
    def __init__(self, result: bool):
        self._result = result
        self.sent_text = None

    def send_message(self, text, parse_mode="HTML"):
        self.sent_text = text
        return self._result


def _fake_balance():
    return {'deposit': 0, 'holdings': []}


def test_send_daily_brief_raises_when_telegram_send_fails(monkeypatch):
    """send_message가 False(발송 실패)면 _send_daily_brief는 예외를 던져야 한다
    (safe_run이 fallback을 타도록). 실패를 '발송 완료'로 로그하면 안 된다."""
    monkeypatch.setattr('src.trade.balance.get_balance', _fake_balance)
    worker = NotifierWorker(PipelineContext(), storage=None)
    worker.tg = _FakeTelegram(result=False)

    with pytest.raises(Exception):
        worker._send_daily_brief('15:00')


def test_send_daily_brief_succeeds_when_telegram_send_succeeds(monkeypatch):
    """send_message가 True면 예외 없이 통과해야 한다."""
    monkeypatch.setattr('src.trade.balance.get_balance', _fake_balance)
    worker = NotifierWorker(PipelineContext(), storage=None)
    worker.tg = _FakeTelegram(result=True)

    worker._send_daily_brief('15:00')  # 예외 없이 통과해야 함
    assert worker.tg.sent_text is not None


def test_two_brief_slots_are_independent(tmp_path):
    """12시를 보내도 15시 슬롯은 따로 열린다."""
    from src.report import gate
    noon = datetime(2026, 9, 1, 12, 5)
    close = datetime(2026, 9, 1, 15, 5)

    assert gate.brief_due(noon, str(tmp_path)) == '12:00'
    gate.mark_sent('12:00', noon, str(tmp_path))
    assert gate.brief_due(noon, str(tmp_path)) is None
    assert gate.brief_due(close, str(tmp_path)) == '15:00'


def test_noon_brief_title_names_the_window():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, datetime(2026, 9, 1, 12, 5), '12:00')
    assert '12:00' in msg and '09:00~12:00' in msg


def test_close_brief_title_is_unchanged():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, datetime(2026, 9, 1, 15, 5), '15:00')
    assert '15:00 마감 브리핑' in msg


def test_ticker_count_respects_the_window(tmp_path):
    """09:00~12:00 창이면 그 밖의 거래는 세지 않는다."""
    from src.pipeline.daily_brief import _count_today_tickers
    csv_path = tmp_path / 'hist.csv'
    csv_path.write_text(
        'timestamp,symbol\n'
        '2026-09-01 09:30:00,AAA\n'
        '2026-09-01 14:30:00,BBB\n',
        encoding='utf-8')

    assert _count_today_tickers(str(csv_path), '2026-09-01') == 2
    assert _count_today_tickers(str(csv_path), '2026-09-01',
                                since='09:00', until='12:00') == 1
