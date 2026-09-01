"""심3의 7일 타임스탑은 배포 이래 한 번도 발동하지 않았다.

2026-08-13 심 전체 감사에서 드러났다. 청산 블록이 `date.fromisoformat()`을
부르는데 `date`가 import돼 있지 않았고, 그 자리를 감싼 `except Exception: pass`가
NameError를 통째로 삼켰다.

    entry_date = date.fromisoformat(entry_date_str)   # NameError
    ...
    except Exception:
        pass                                          # 조용히 사라진다

조용한 실패는 없는 기능과 같다. 로그에도 안 남으니 "타임스탑이 안 걸리는 날이
많네"와 "타임스탑이 아예 없다"가 구분되지 않았다.

같이 넣는 진입 깔때기는 심5·심9와 같은 목적이다 — 심3은 8월 매수가 1건뿐인데
이유가 로그에 없었다. 의심은 유니버스(get_finance_ratio_rank = ROE 수익성 상위)와
진입 조건(섹터 평균 대비 20% 저평가)이 서로 밀어낸다는 것이다. 고ROE는 대개
고PER/PBR이다. 추측으로 유니버스를 바꾸지 않고 먼저 센다.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.sim3_risk import SmartRiskSimulator


def _sim():
    s = SmartRiskSimulator(initial_cash=3_000_000)
    s.save_state = lambda *a, **k: None
    return s


def test_timestop_fires_after_seven_days():
    """이게 배포 이래 죽어 있던 경로다."""
    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': '2026-01-01', 'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})   # 손익 +1% — 익절·손절 미해당

    assert '005930' not in sim.state['portfolio'], '7일 지난 포지션은 타임스탑으로 청산돼야 한다'


def test_recent_entry_is_not_timestopped():
    from src.strategy.simulators.base_simulator import get_kst_date

    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': get_kst_date().isoformat(),
        'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})

    assert '005930' in sim.state['portfolio']


def test_unparsable_entry_date_is_reported_not_swallowed(capsys):
    """모르는 것을 조용히 넘기면 그 기능이 죽은 걸 아무도 모른다."""
    sim = _sim()
    sim.state['portfolio']['005930'] = {
        'name': '삼성전자', 'quantity': 10, 'avg_price': 1000,
        'peak_price': 1000, 'entry_date': '(없음)', 'is_scaled_out': False,
    }

    sim.run([], current_prices={'005930': 1010})

    assert '타임스탑 판정 실패' in capsys.readouterr().out
    assert '005930' in sim.state['portfolio'], '판정 실패로 포지션을 잃으면 안 된다'


def test_funnel_reports_the_gate_that_blocked(capsys):
    """거래대금 문턱(50억)에서 전량 걸리는지, 저평가에서 걸리는지 갈라야
    유니버스를 바꿀지 조건을 바꿀지 정할 수 있다."""
    sim = _sim()
    cheap_but_thin = {'code': '000001', 'name': '얇은주', 'price': 1000,
                      'amount': 1_000_000, 'per': 1.0, 'pbr': 0.1,
                      'sector_name': '반도체'}

    sim.run([cheap_but_thin], current_prices={})

    out = capsys.readouterr().out
    assert '[Sim3 깔때기]' in out
    assert 'amount' in out


# ── 깔때기 회계 불변식 (2026-09-01) ──────────────────────────────────
#
# 그날 실전 매매가 0건이었는데 로그는 이랬다:
#     [Sim3 깔때기] 후보 30 | 탈락: amount 17, not_cheap 5, adx 1
# 30 ≠ 23인데 아무도 몰랐다. 보유·쿨다운 갈래가 기록 없이 빠져나갔기 때문이다.
# 수를 안 맞춰보면 구멍은 영원히 안 보인다.

def _candidate(code, **kw):
    base = {'code': code, 'name': code, 'price': 10_000,
            'amount': 10_000_000_000, 'per_ttm': 1.0, 'pbr_ttm': 0.1,
            'sector_name': '전기·전자', 'sparkline_price': [100] * 10}
    base.update(kw)
    return base


def test_funnel_accounts_for_every_candidate():
    """후보 = 매수 + 탈락. 남으면 어딘가가 이유 없이 후보를 버리고 있다."""
    from src.strategy.simulators.sim3_risk import SmartRiskSimulator as S
    cands = [_candidate(f'{i:06d}') for i in range(10)]
    funnel = [{'code': c['code'], 'reason': 'amount'} for c in cands[:7]]
    n, bought, rejected, unexplained = S.funnel_accounting(cands, funnel, bought=3)
    assert (n, bought, rejected, unexplained) == (10, 3, 7, 0)


def test_funnel_flags_the_2026_09_01_hole():
    """그날의 로그를 그대로 재현하면 미설명이 잡혀야 한다.

    후보 30, 기록된 탈락 23(amount 17 + not_cheap 5 + adx 1), 매수 0.
    7개가 설명되지 않는다 — 이 수가 0이 아닌 것이 신호였다.
    """
    from src.strategy.simulators.sim3_risk import SmartRiskSimulator as S
    cands = [_candidate(f'{i:06d}') for i in range(30)]
    funnel = ([{'code': 'x', 'reason': 'amount'}] * 17
              + [{'code': 'x', 'reason': 'not_cheap'}] * 5
              + [{'code': 'x', 'reason': 'adx'}])
    _, _, _, unexplained = S.funnel_accounting(cands, funnel, bought=0)
    assert unexplained == 7, '2026-09-01의 구멍이 감지되지 않는다'


def test_early_exit_is_not_reported_as_unexplained():
    """보유 상한으로 끊긴 건 '평가 안 함'이지 '설명 못 함'이 아니다.

    다만 그 판정은 **실제로 몇 개를 봤는지(seen)** 로만 해야 한다. 처음에는
    "funnel에 max_holdings가 있으면 미설명 0"으로 했는데, 그건 포트폴리오가
    꽉 찬 날마다 진짜 구멍을 통째로 가리는 스위치였다 — 감시를 끄는 스위치를
    감시 안에 둔 셈이라 리뷰에서 잡혔다.
    """
    from src.strategy.simulators.sim3_risk import SmartRiskSimulator as S
    cands = [_candidate(f'{i:06d}') for i in range(30)]
    funnel = [{'code': '000001', 'reason': 'max_holdings', 'held': 5}]
    # 첫 후보에서 끊겼으니 본 것은 1개다
    _, _, _, unexplained = S.funnel_accounting(cands, funnel, bought=0, seen=1)
    assert unexplained == 0


def test_early_exit_still_reports_a_real_hole():
    """조기종료가 있어도 그전에 조용히 사라진 후보는 잡혀야 한다.

    max_holdings 한 줄이 미설명을 0으로 만들던 버전에서는 이게 통과했다.
    """
    from src.strategy.simulators.sim3_risk import SmartRiskSimulator as S
    cands = [_candidate(f'{i:06d}') for i in range(30)]
    # 10개를 봤는데 기록은 max_holdings 하나뿐 — 9개가 조용히 사라졌다
    funnel = [{'code': '000010', 'reason': 'max_holdings', 'held': 5}]
    _, _, _, unexplained = S.funnel_accounting(cands, funnel, bought=0, seen=10)
    assert unexplained == 9, '조기종료 뒤에 숨은 구멍을 못 잡는다'


def test_failed_buy_is_not_counted_as_a_purchase():
    """buy()는 현금 부족이면 False다. 그걸 매수로 세면 회계가 맞아버려 구멍이 가려진다.

    자금 부족은 실전에서 "왜 안 샀나"의 가장 흔한 답이라 더 위험하다.
    """
    # 실전에서 나는 형태: 대부분 투자돼 있고 현금만 바닥이다. NAV 기준 사이징은
    # 살 수량을 크게 잡는데 정작 지불할 현금이 없다.
    sim = _sim()
    sim.state['cash'] = 1_000
    sim.state['portfolio']['999999'] = {
        'name': 'HELD', 'quantity': 300, 'avg_price': 10_000,
        'peak_price': 10_000, 'entry_date': '2026-09-01', 'is_scaled_out': False}
    captured = {}
    sim._log_funnel = lambda c, f, b=0, s=None: captured.update(funnel=f, bought=b)
    sim.run([_candidate('000001', sparkline_price=[100 + 3 * i for i in range(12)])],
            current_prices={'999999': 10_000, '000001': 10_000})
    assert captured['bought'] == 0, '실패한 매수가 매수로 집계됐다'
    assert 'insufficient_cash' in [x['reason'] for x in captured['funnel']],         f"자금 부족이 기록되지 않았다: {[x['reason'] for x in captured['funnel']]}"


def test_holdings_and_cooldown_are_recorded():
    """오늘 실제로 샜던 두 갈래가 이제 이유를 남기는지 — 런타임으로 확인한다.

    정적 검사(test_decision_logging_coverage)는 `_fn` 호출이 있는지만 본다.
    실제로 그 값이 깔때기에 담기는지는 심을 돌려봐야 안다.
    """
    sim = _sim()
    sim.state['portfolio']['000001'] = {
        'name': 'A', 'quantity': 1, 'avg_price': 10_000,
        'peak_price': 10_000, 'entry_date': '2026-09-01', 'is_scaled_out': False}
    sim.state['cooldown_codes'] = {'000002': '2099-01-01'}

    captured = {}
    orig = sim._log_funnel

    def spy(candidates, funnel, bought=0, seen=None):
        captured['reasons'] = [f['reason'] for f in funnel]
        return orig(candidates, funnel, bought, seen)

    sim._log_funnel = spy
    sim.run([_candidate('000001'), _candidate('000002')],
            current_prices={'000001': 10_000})

    assert 'held_or_sold_today' in captured['reasons'], '보유 종목이 기록 없이 사라진다'
    assert 'cooldown' in captured['reasons'], '쿨다운 종목이 기록 없이 사라진다'
