"""깔때기 회계 — "후보 = 매수 + 탈락"이 실제로 맞는가.

2026-09-01에 전 심의 결정 기록을 채우고 나서, **그 계측이 곧바로 오회계 세 건을
드러냈다.** 셋 다 "수는 맞는데 종목이 사라진" 형태라 숫자만 봐서는 안 보였다.

  1. 심9는 진입 시각 창(14:30~15:20) 밖이면 후보를 보지도 않고 return했다.
     기록이 없어 로그가 "후보 N인데 탈락 기록이 없다"로 찍혔고 **정상 스킵이
     배선 고장처럼 보였다.**
  2. US유동성은 랭킹 전 컴프리헨션에서 후보를 걸렀다. 실측 20종목 중 15개가
     사라졌는데 로그는 "후보 5 → 매수 5 (전량 진입)"으로 깨끗했다. 그중 5개는
     avg_dollar_volume 결손 — 같은 커밋이 us_sim1·2에는 전용 이유를 만든 고장이다.
  3. `buys >= n`이 **모집단보다 많이 산 경우**까지 '전량 진입'으로 삼켰다.

셋 다 로그 코드의 결함이지 전략의 결함이 아니다. 그래서 여기서 고정한다 —
계측이 거짓말하면 그 위에서 내리는 모든 판단이 거짓이 된다.
"""
import io
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategy.simulators.base_simulator import log_funnel  # noqa: E402


def _capture(fn, *a, **kw) -> str:
    """log_funnel의 출력을 문자열로 잡는다."""
    buf, old = io.StringIO(), sys.stdout
    sys.stdout = buf
    try:
        fn(*a, **kw)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ── log_funnel의 회계 분기 ────────────────────────────────────────────

def test_full_entry_is_not_a_warning():
    """전량 매수했으면 탈락 기록이 없는 게 맞다.

    여기서 경고하면 정상 상황에 경고가 뜨고, 상시 뜨는 경고는 아무도 안 본다.
    """
    out = _capture(log_funnel, 'X', range(3), [], buys=3)
    assert '전량 진입' in out and '⚠️' not in out


def test_buying_more_than_the_population_is_an_error():
    """모집단보다 많이 샀다 = 회계가 깨졌다(장부를 섞었거나 모집단을 잘못 넘겼다).

    `buys >= n`으로 두면 이걸 '전량 진입'으로 삼킨다. 이 시스템에서 회계
    불일치를 잡는 검사는 여기 하나뿐이라, 삼키면 아무도 못 잡는다.
    """
    out = _capture(log_funnel, 'X', range(3), [], buys=7)
    assert '⚠️' in out and '회계가 깨졌다' in out


def test_silent_loss_is_a_warning():
    """후보는 있는데 산 것도 버린 이유도 없으면 그게 사고다."""
    out = _capture(log_funnel, 'X', range(5), [], buys=0)
    assert '⚠️' in out and '탈락 기록이 없다' in out


def test_early_break_is_not_reported_as_unexplained():
    """`break`로 끊은 뒤 후보는 '평가 안 함'이지 '설명 못 함'이 아니다.

    심마다 이유 이름이 다르므로(max_holdings / below_rank_cutoff) 둘 다 인정한다.
    """
    for reason in ('max_holdings', 'below_rank_cutoff'):
        out = _capture(log_funnel, 'X', range(30),
                       [{'code': 'A', 'reason': reason}], buys=0)
        assert '⚠️' not in out, f'{reason}가 조기종료로 인정되지 않는다'


def test_continue_style_sim_still_gets_the_warning():
    """max_holdings에서 `continue`하는 심(심8)은 끝까지 본다.

    break 심과 같이 취급해 경고를 끄면, 포트폴리오가 찬 날마다 게이트가 가장
    많은 심에서 감시가 통째로 사라진다.
    """
    out = _capture(log_funnel, 'X', range(30),
                   [{'code': 'A', 'reason': 'max_holdings'}], buys=0,
                   early_exit_breaks=False)
    assert '미설명' in out


# ── 심9: 시각 창 밖이면 그 이유가 남아야 한다 ─────────────────────────

def test_sim9_records_why_it_skipped_outside_the_window():
    """창 밖 스킵이 '탈락 기록 없음'으로 보이면 정상이 고장처럼 읽힌다."""
    import datetime as dt

    from src.strategy.simulators.sim9_gap_fade import decide_gap_fade

    view = {'portfolio': {}, 'cooldown_codes': {}, 'nav': 3_000_000}
    funnel = []
    orders = decide_gap_fade(view, [{'code': '000001', 'name': 'A', 'price': 100}],
                             {}, now=dt.datetime(2026, 9, 1, 10, 0), funnel=funnel)
    assert orders == []
    assert [f['reason'] for f in funnel] == ['outside_entry_window']


# ── US유동성: 랭킹 전에 사라지는 종목이 없어야 한다 ────────────────────

def test_us_liquidity_records_pre_ranking_drops():
    """컴프리헨션으로 거르면 깔때기에도 AST 게이트에도 안 잡힌다.

    게이트는 루프의 continue/break만 본다 — 컴프리헨션 필터는 구조적으로
    보이지 않는다. 실측에서 20종목 중 15개가 이렇게 사라졌다.
    """
    from src.strategy.simulators.us_sim3_liquidity import decide_us_liquidity

    view = {'portfolio': {}, 'cooldown_codes': {}, 'nav': 20_000}
    cands = (
        [{'code': f'OK{i}', 'name': 'x', 'price': 10, 'avg_dollar_volume': 9e9}
         for i in range(5)]
        + [{'code': f'NOADV{i}', 'name': 'x', 'price': 10} for i in range(5)]
        + [{'code': f'NOPRICE{i}', 'name': 'x', 'price': 0,
            'avg_dollar_volume': 9e9} for i in range(5)])
    funnel = []
    decide_us_liquidity(view, cands, {}, sched={}, funnel=funnel)

    reasons = [f['reason'] for f in funnel]
    assert reasons.count('no_dollar_volume') == 5, '거래대금 결손이 기록되지 않는다'
    assert reasons.count('no_price') == 5, '가격 결손이 기록되지 않는다'


def test_us_liquidity_records_why_it_skipped_a_non_rebalance_day():
    """이 심은 20거래일에 한 번만 움직인다 — 기록이 없으면 런의 95%에서 경고가 뜬다."""
    from src.strategy.simulators.us_sim3_liquidity import decide_us_liquidity

    view = {'portfolio': {}, 'cooldown_codes': {}, 'nav': 20_000}
    funnel = []
    orders = decide_us_liquidity(view, [{'code': 'AAPL', 'price': 10,
                                         'avg_dollar_volume': 9e9}], {},
                                 sched={'elapsed': 1}, funnel=funnel)
    assert orders == []
    assert [f['reason'] for f in funnel] == ['not_rebalance_day']
