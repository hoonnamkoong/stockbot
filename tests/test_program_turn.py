"""프로그램 매매 턴 회계 순수 함수 테스트.

턴 = 프로그램 ON부터 OFF까지. 기준가(basis)는 턴 시작·스위칭 시점에 MTM 리셋된다.
핵심 불변식: 모든 턴의 손익 합 = 평단 기준 누적 실현손익.
"""

from src.pipeline.workers.program_turn import (
    new_turn, switch_tag, record_buy, record_sell, prune_basis,
)


def _pos(qty, avg, tag=None):
    p = {"name": "테스트", "quantity": qty, "avg_price": avg}
    if tag:
        p["tag"] = tag
    return p


def test_new_turn_uses_opening_basis_over_current_price():
    """ON 시점 스냅샷(opening_basis)이 있으면 그것을 기준가로 쓴다."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_200_000, positions,
                    opening_basis={"005930": 3500}, current_prices={"005930": 3600})
    assert turn["basis"]["005930"] == 3500
    assert turn["capital"] == 1_200_000
    assert turn["by_tag"] == {}
    assert turn["active_tag"] is None


def test_new_turn_falls_back_to_current_price():
    """opening_basis가 비어 있으면(ON 시 잔고 조회 실패) 현재가로 채운다."""
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions, opening_basis={}, current_prices={"005930": 3600})
    assert turn["basis"]["005930"] == 3600


def test_first_tag_assignment_keeps_opening_basis():
    """턴 첫 실행(active_tag=None)은 기준가를 덮어쓰지 않는다.

    ON 시점(3500)부터 첫 실행(3600) 사이의 변동은 첫 태그의 몫이어야 한다.
    여기서 기준가를 3600으로 리셋하면 그 100원이 어느 턴에도 안 잡힌다.
    """
    positions = {"005930": _pos(10, 3000)}
    turn = new_turn("t1", 1_000_000, positions, {"005930": 3500}, {})
    switch_tag(turn, positions, "sim4_bull_daytrading", {"005930": 3600})
    assert turn["basis"]["005930"] == 3500          # 리셋되지 않음
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


def test_turn_pnl_sum_equals_cumulative_realized_pnl():
    """핵심 불변식: 턴별 손익의 합 = 평단 기준 누적 실현손익.

    턴1(sim4): 3000에 10주 매수 → OFF 시점 3500 (미실현 +5000, 턴1 몫으로 동결)
    턴2(sim5): 기준가 3500으로 리셋 → 3700에 전량 매도 (턴2 몫 +2000)
    평단 기준 누적 실현손익 = (3700-3000)*10 = +7000 = 5000 + 2000
    """
    positions = {"005930": _pos(10, 3000)}

    # ── 턴1: 매수 후 미실현 상태로 OFF
    turn1 = new_turn("t1", 1_000_000, {}, {}, {})
    switch_tag(turn1, {}, "sim4_bull_daytrading", {})
    record_buy(turn1, "005930", qty=10, price=3000, prev_qty=0)
    positions["005930"]["tag"] = "sim4_bull_daytrading"
    # OFF 시점 동결(TS의 computeTurnPnl과 동일한 계산): by_tag + 보유분 미실현
    off_price = 3500
    turn1_pnl = sum(turn1["by_tag"].values()) + (off_price - turn1["basis"]["005930"]) * 10
    assert turn1_pnl == 5000

    # ── 턴2: 기준가가 OFF 시점 시세로 리셋되어 시작
    turn2 = new_turn("t2", 1_005_000, positions,
                     opening_basis={"005930": off_price}, current_prices={})
    switch_tag(turn2, positions, "sim5_sideways", {"005930": off_price})
    record_sell(turn2, positions, "005930", qty=10, price=3700)
    del positions["005930"]
    prune_basis(turn2, positions)
    turn2_pnl = sum(turn2["by_tag"].values())
    assert turn2_pnl == 2000
    assert turn2["by_tag"]["sim5_sideways"] == 2000

    # ── 불변식
    cumulative_realized = (3700 - 3000) * 10      # program_trader의 realized_pnl 계산식
    assert turn1_pnl + turn2_pnl == cumulative_realized == 7000


# ── 활성 태그 결정 (program_trader) ──────────────────────────────────
from src.pipeline.workers.program_trader import _resolve_active_tag


def test_normal_sim_tag_is_sim_id():
    """일반 심은 자기 id가 곧 태그다 — 턴 안에서 바뀌지 않는다."""
    assert _resolve_active_tag("sim5_sideways", {}) == "sim5_sideways"
    assert _resolve_active_tag("sim7_report_follower", {"active_regime": "BULL"}) == "sim7_report_follower"


def test_sim10_tag_follows_active_regime():
    """Sim10만 하위 전략으로 분해된다. active_regime은 Sim10이 run() 중 스냅샷에 쓴 값."""
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BULL"}) == "sim4_bull_daytrading"
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "SIDEWAYS"}) == "sim5_sideways"
    assert _resolve_active_tag("sim10_orchestrator", {"active_regime": "BEAR"}) == "cash"


def test_sim10_unknown_regime_falls_back_to_sim_id():
    """국면을 못 읽었으면(스냅샷 오염 등) 심 id로 폴백 — 손익이 유실되지 않는다."""
    assert _resolve_active_tag("sim10_orchestrator", {}) == "sim10_orchestrator"
