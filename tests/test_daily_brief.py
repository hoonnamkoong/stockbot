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
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, NOW)
    assert '07/22 (수)' in msg
    assert '1,240,000원' in msg          # 예수금
    assert '5,250,000원' in msg          # 보유총액 = 10*300000 + 5*450000
    assert '+250,000원' in msg           # 평가손익 = 150000 + 100000
    assert '+5.00%' in msg               # 250000 / (5250000-250000)


def test_brief_lists_every_sim_with_rate_and_count():
    msg = build_daily_brief(OK_BALANCE, OK_SIMS, NOW)
    assert '심리 괴리형 (Sim 1)' in msg
    assert '-1.11%' in msg
    assert '6종목' in msg
    assert '가치 페어형 (Sim 3)' in msg
    assert '+0.00%' in msg
    assert '0종목' in msg


def test_brief_reports_balance_error_without_dropping_sims():
    msg = build_daily_brief({'error': 'KIS API 오류: 토큰 만료', 'holdings': []}, OK_SIMS, NOW)
    assert '조회 실패' in msg
    assert 'KIS API 오류: 토큰 만료' in msg
    assert '1,240,000원' not in msg
    assert '심리 괴리형 (Sim 1)' in msg   # 심 블록은 살아있어야 한다


def test_brief_no_holdings_shows_dash_not_zero_percent():
    """분모(매입원가)가 0이면 수익률은 0%가 아니라 모르는 값이다."""
    msg = build_daily_brief({'deposit': 3_000_000, 'holdings': []}, OK_SIMS, NOW)
    assert '3,000,000원' in msg
    assert '—' in msg
    assert '0.00%' not in msg.split('🤖')[0]   # 계좌 블록 한정


def test_brief_sim_without_raw_stats_marked_unmeasurable():
    sims = [{'label': '하락 줍줍형 (Sim 6)', 'profit_rate': None, 'ticker_count': 0}]
    msg = build_daily_brief(OK_BALANCE, sims, NOW)
    assert '측정 불가' in msg
    assert '하락 줍줍형 (Sim 6)' in msg


import json
from src.pipeline.daily_brief import collect_sim_brief, SIM_BRIEF_TARGETS


def test_targets_cover_nine_sims():
    assert len(SIM_BRIEF_TARGETS) == 9
    states = [t[1] for t in SIM_BRIEF_TARGETS]
    assert 'sim_psych_state.json' in states
    assert 'sim_orchestrator_state.json' in states
    assert 'sim_libero_state.json' not in states   # 분석기는 제외


def _write(tmp_path, name, text):
    (tmp_path / name).write_text(text, encoding='utf-8')


def test_collect_reads_raw_stats_and_counts_distinct_tickers(tmp_path):
    _write(tmp_path, 'sim_psych_state.json',
           json.dumps({'raw_stats': {'profit_rate': -1.11}}))
    _write(tmp_path, 'trade_history_sim_psych.csv',
           'timestamp,symbol,action,price,quantity,total_amount,reason\n'
           '2026-07-22 09:10:00,금호타이어(073240),BUY,6270,47,294690,x\n'
           '2026-07-22 14:10:00,금호타이어(073240),SELL,6400,47,300800,x\n'
           '2026-07-22 11:00:00,LG디스플레이(034220),BUY,10160,29,294640,x\n'
           '2026-07-21 11:00:00,대우건설(047040),BUY,14800,19,281200,x\n')

    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    psych = next(r for r in rows if 'Sim 1' in r['label'])
    assert psych['profit_rate'] == -1.11
    assert psych['ticker_count'] == 2   # 같은 종목 2회 = 1종목, 어제 건은 제외


def test_collect_missing_files_are_unmeasurable_not_zero(tmp_path):
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    assert len(rows) == 9
    assert all(r['profit_rate'] is None for r in rows)   # 상태 없음 = 모름
    assert all(r['ticker_count'] == 0 for r in rows)     # CSV 없음 = 거래 없음


def test_collect_state_without_raw_stats_is_unmeasurable(tmp_path):
    _write(tmp_path, 'sim_bear_state.json', json.dumps({'cash': 3000000}))
    rows = collect_sim_brief(str(tmp_path), '2026-07-22')
    bear = next(r for r in rows if 'Sim 6' in r['label'])
    assert bear['profit_rate'] is None


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


def test_brief_only_at_15h_notify_round():
    assert should_send_brief(should_notify=True,  hour=15) is True
    assert should_send_brief(should_notify=True,  hour=14) is False
    assert should_send_brief(should_notify=True,  hour=9)  is False
    assert should_send_brief(should_notify=False, hour=15) is False
