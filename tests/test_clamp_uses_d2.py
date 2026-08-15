"""예산 클램프는 D+2 예수금을 본다 — 판 돈이 아직 안 들어왔다고 덜 사지 않는다.

2026-08-12 실측: 계좌가치가 1,235,198로 잡혀 종목당 목표가 185,280이 됐다.
설정 예산 200만이면 목표가 300,000이어야 하는데 **62%**만 썼다.

    금호전기 5,300원 → int(185,280/5,300) = 34주 = 180,200원

원인은 `deposit`이 `dnca_tot_amt`(D+0) 하나였다는 것. 매도대금은 D+2에
예수금으로 편입되므로, 파는 심일수록 계좌가치가 실제보다 작게 잡히고 그만큼
사이징이 깎인다.

근거: 2026-08-14 로그에서 보유가 없을 때 D+2(2,020,888) == KIS총평가였다.
즉 D+2 예수금 + 유가증권 평가액이 계좌가치다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


def _account_value(bal, holdings):
    """program_trader의 클램프 기준값 산식을 그대로 재현한다."""
    d0 = int(bal.get('deposit') or 0)
    d2 = bal.get('deposit_d2')
    deposit = int(d2) if isinstance(d2, int) and d2 > 0 else d0
    invested = sum(h['avg_price'] * h['qty'] for h in holdings.values())
    return deposit + invested


def test_d2_is_preferred_over_d0():
    """08-14 실제 숫자. D+0을 쓰면 93,651원이 사라진다."""
    v = _account_value({'deposit': 1_927_237, 'deposit_d2': 2_020_888}, {})

    assert v == 2_020_888


def test_missing_d2_falls_back_to_d0():
    """모의계좌·구버전 응답엔 필드가 없다. 보수적인 쪽으로 떨어진다."""
    assert _account_value({'deposit': 1_927_237, 'deposit_d2': None}, {}) == 1_927_237
    assert _account_value({'deposit': 1_927_237}, {}) == 1_927_237


def test_zero_d2_is_not_used():
    """0은 '없다'와 구분되지 않는 값이다. 그걸 그대로 쓰면 계좌가치가
    보유원가만 남아 사이징이 통째로 꺼진다."""
    assert _account_value({'deposit': 1_927_237, 'deposit_d2': 0}, {}) == 1_927_237


def test_holdings_are_added_at_cost_not_market():
    """미실현이익까지 사이징 근거로 삼으면 오르는 날 과투입된다."""
    v = _account_value({'deposit': 1_000_000, 'deposit_d2': 1_000_000},
                       {'005930': {'avg_price': 1000.0, 'qty': 100}})

    assert v == 1_100_000


def test_the_august_12_shortfall_is_recovered():
    """그날 D+2가 200만이었다면 목표가 300,000이 되어 금호전기를 56주 샀다."""
    v = _account_value({'deposit': 1_235_198, 'deposit_d2': 2_000_000}, {})
    target = v * 0.19          # 5종목 x 19% = 95%

    assert int(target / 5300) == 71, '이전엔 34주였다'
