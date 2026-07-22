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
