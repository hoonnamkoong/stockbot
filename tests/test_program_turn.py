"""프로그램 매매 턴 회계 순수 함수 테스트.

턴 = 프로그램 ON부터 OFF까지. 기준가(basis)는 턴 시작 시점에 **매입 평단**으로 seed된다
(ON 시점 시세로 리셋하지 않는다). 그래서 ON 전부터 보유한 종목도 원래 매입가부터 손익을
재고, 턴 손익이 KIS 종목별 ROI와 정합한다. 스위칭 시에는 여전히 직전 태그 구간을 락인하고
기준가를 리셋하지만, seed가 평단이므로 구간 합은 평단 기준으로 telescoping된다.
"""

from src.pipeline.workers.program_turn import (
    new_turn, switch_tag, record_buy, record_sell, prune_basis,
)


def _pos(qty, avg, tag=None):
    p = {"name": "테스트", "quantity": qty, "avg_price": avg}
    if tag:
        p["tag"] = tag
    return p


def test_new_turn_uses_avg_price_ignoring_on_snapshot():
    """(B) 기준가 = 매입 평단. ON 시점 시세 스냅샷(opening_basis/current)은 무시한다.

    턴 손익을 원래 매입가부터 계산해 KIS 종목별 ROI와 정합시키기 위함.
    """
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_200_000, positions,
                    opening_basis={"005930": 3500}, current_prices={"005930": 3600})
    assert turn["basis"]["005930"] == 3000.0        # 평단, ON 시세(3500/3600) 아님
    assert turn["capital"] == 1_200_000
    assert turn["by_tag"] == {}
    assert turn["active_tag"] is None


def test_new_turn_uses_avg_price_even_with_no_snapshot():
    """스냅샷이 없어도 평단을 기준가로 쓴다(현재가 폴백 아님)."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions)
    assert turn["basis"]["005930"] == 3000.0


def test_first_tag_assignment_keeps_avg_basis():
    """턴 첫 실행(active_tag=None)은 기준가를 덮어쓰지 않는다 — 평단을 유지한다."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions)      # basis = 평단 3000
    switch_tag(turn, positions, "sim4_bull_daytrading", {"005930": 3600})
    assert turn["basis"]["005930"] == 3000.0         # 리셋되지 않음(평단 유지)
    assert turn["active_tag"] == "sim4_bull_daytrading"
    assert positions["005930"]["tag"] == "sim4_bull_daytrading"
    assert turn["by_tag"] == {}                      # 락인할 직전 태그가 없음


def test_switch_locks_in_previous_tag_and_resets_basis():
    """스위칭 시 직전 태그가 자기 구간의 평가손익을 확정 귀속받고, 기준가가 리셋된다."""
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim4_bull_daytrading"}

    switch_tag(turn, positions, "sim5_sideways", {"005930": 3500})

    assert turn["by_tag"]["sim4_bull_daytrading"] == 5000.0   # (3500-3000)*10
    assert turn["basis"]["005930"] == 3500
    assert turn["active_tag"] == "sim5_sideways"
    assert positions["005930"]["tag"] == "sim5_sideways"


def test_switch_to_same_tag_is_noop():
    positions = {"005930": _pos(10, 3000, tag="sim5_sideways")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    switch_tag(turn, positions, "sim5_sideways", {"005930": 3500})
    assert turn["by_tag"] == {}
    assert turn["basis"]["005930"] == 3000


def test_switch_without_price_keeps_position_on_old_tag():
    """시세가 없으면 락인할 수 없다 — 그 종목은 직전 태그·기준가를 유지한다."""
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim4_bull_daytrading"}
    switch_tag(turn, positions, "sim5_sideways", {})     # 시세 없음
    assert positions["005930"]["tag"] == "sim4_bull_daytrading"
    assert turn["basis"]["005930"] == 3000
    assert turn["active_tag"] == "sim5_sideways"


def test_record_buy_sets_basis_to_fill_price():
    turn = {"id": "t1", "capital": 1_000_000, "basis": {}, "by_tag": {}, "active_tag": "sim5_sideways"}
    record_buy(turn, "005930", qty=10, price=3000, prev_qty=0)
    assert turn["basis"]["005930"] == 3000.0


def test_record_buy_weights_basis_on_add_on():
    """추가 매수 시 기준가는 평단처럼 가중평균된다."""
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 1000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    record_buy(turn, "005930", qty=10, price=1200, prev_qty=10)
    assert turn["basis"]["005930"] == 1100.0     # (1000*10 + 1200*10) / 20


def test_record_sell_credits_holding_tag_against_basis():
    """매도 손익은 평단이 아니라 기준가 대비로, 그 종목을 들고 있던 태그에 귀속된다."""
    positions = {"005930": _pos(10, 3000, tag="sim5_sideways")}
    turn = {"id": "t2", "capital": 1_000_000, "basis": {"005930": 3500},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    record_sell(turn, positions, "005930", qty=10, price=3700)
    assert turn["by_tag"]["sim5_sideways"] == 2000.0    # (3700-3500)*10


def test_record_sell_credits_stale_tag_when_switch_skipped_it():
    """스위칭 때 시세가 없어 옛 태그·옛 기준가에 남은 종목은, 팔릴 때도 옛 태그 몫이다.

    활성 태그(sim5)에 귀속하면 기준가는 sim4 시절 것(3000)인데 손익은 sim5가 가져가
    SIM별 분해가 엇갈린다. 표시 계산(TS)도 pos.tag를 쓰므로 기준을 일치시킨다.
    """
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3000},
            "by_tag": {}, "active_tag": "sim4_bull_daytrading"}
    switch_tag(turn, positions, "sim5_sideways", {})     # 시세 없음 → 이 종목은 sim4에 남음
    assert positions["005930"]["tag"] == "sim4_bull_daytrading"

    record_sell(turn, positions, "005930", qty=10, price=3700)
    assert turn["by_tag"] == {"sim4_bull_daytrading": 7000.0}   # (3700-3000)*10, sim5 몫 아님


def test_record_sell_falls_back_to_active_tag_when_untagged():
    """태그가 없는 포지션(원장 마이그레이션 전 등)은 활성 태그로 폴백 — 손익이 유실되지 않는다."""
    positions = {"005930": _pos(10, 3000)}               # tag 없음
    turn = {"id": "t2", "capital": 1_000_000, "basis": {"005930": 3500},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    record_sell(turn, positions, "005930", qty=10, price=3700)
    assert turn["by_tag"]["sim5_sideways"] == 2000.0


def test_prune_basis_drops_sold_out_codes():
    turn = {"id": "t1", "capital": 1_000_000, "basis": {"005930": 3500, "000660": 1000},
            "by_tag": {}, "active_tag": "sim5_sideways"}
    prune_basis(turn, {"000660": _pos(5, 1000)})
    assert "005930" not in turn["basis"]
    assert "000660" in turn["basis"]


def test_carried_in_position_pnl_measured_from_avg_price():
    """(B) ON 전부터 보유한 종목은 매입 평단부터 손익을 잰다 — ON 시세로 리셋하지 않는다.

    3000에 10주 산 종목을 안 팔고 다음 턴으로 넘긴 뒤, ON 시점 시세가 3500이어도
    턴은 평단 3000으로 열린다. 3700에 전량 매도하면 턴 실현손익 = (3700-3000)*10 = 7000.
    (구 설계는 ON 시세 3500으로 리셋해 2000만 잡았다 — 이제 KIS 종목별 ROI와 정합.)
    """
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    # 라우트가 ON 시점 시세(3500) 스냅샷을 넘겨도 무시하고 평단으로 연다.
    turn = new_turn("t2", 1_000_000, positions, opening_basis={"005930": 3500})
    switch_tag(turn, positions, "sim5_sideways", {"005930": 3600})   # 첫 태그 배정
    record_sell(turn, positions, "005930", qty=10, price=3700)
    del positions["005930"]
    prune_basis(turn, positions)

    assert turn["by_tag"]["sim5_sideways"] == 7000.0        # (3700-3000)*10, 평단 기준
    assert sum(turn["by_tag"].values()) == 7000.0


def test_intra_turn_switch_still_telescopes_to_avg_basis():
    """스위칭이 있어도 턴 총손익은 평단 기준으로 일관된다(구간 분할 합 = 전체).

    평단 3000 → sim4 구간(3000→3500, +5000) 락인 후 sim5로 전환 →
    sim5 구간(3500→3700, +2000) 매도. 합 = 7000 = (3700-3000)*10.
    """
    positions = {"005930": _pos(10, 3000, tag="sim4_bull_daytrading")}
    turn = new_turn("t1", 1_000_000, positions)              # basis = 평단 3000
    switch_tag(turn, positions, "sim4_bull_daytrading", {"005930": 3000})  # 첫 태그
    switch_tag(turn, positions, "sim5_sideways", {"005930": 3500})         # sim4 락인 +5000
    record_sell(turn, positions, "005930", qty=10, price=3700)            # sim5 +2000

    assert turn["by_tag"]["sim4_bull_daytrading"] == 5000.0
    assert turn["by_tag"]["sim5_sideways"] == 2000.0
    assert sum(turn["by_tag"].values()) == 7000.0            # 평단 기준 전체와 일치


# ── 활성 태그 결정 (program_trader) ──────────────────────────────────
from src.pipeline.workers.program_trader import _resolve_active_tag


def test_normal_sim_tag_is_sim_id():
    """일반 심은 자기 id가 곧 태그다 — 턴 안에서 바뀌지 않는다."""
    assert _resolve_active_tag("sim5_sideways", {}) == "sim5_sideways"
    assert _resolve_active_tag("sim_risk", {"active_regime": "BULL"}) == "sim_risk"


def test_sim10_tag_follows_active_regime():
    """Sim10만 하위 전략으로 분해된다. active_regime은 Sim10이 run() 중 스냅샷에 쓴 값."""
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BULL"}) == "sim4_bull_daytrading"
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "SIDEWAYS"}) == "sim5_sideways"
    # BEAR는 2026-07-21 재설계 전까지 '현금 대기'였다. 지금은 Sim6가 인버스 ETF를
    # 추세추종하는 실제 매매 구간이라 손익이 붙을 태그가 필요하다.
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BEAR"}) == "sim6"


def test_sim10_unknown_regime_falls_back_to_sim_id():
    """국면을 못 읽었으면(스냅샷 오염 등) 심 id로 폴백 — 손익이 유실되지 않는다."""
    assert _resolve_active_tag("sim10_orchestrator", {}) == "sim10_orchestrator"
