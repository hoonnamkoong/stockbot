import json
import os
from datetime import datetime

from .base_simulator import BaseSimulator, get_kst_now


class Sim10OrchestratorSimulator(BaseSimulator):
    """
    [Sim 10] 오케스트레이터 — Sim0 국면에 따라 전략 파라미터를 동적 전환.

    Sim0(리베로)의 bull_score + current_regime을 매일 읽어
    BULL/SIDEWAYS/BEAR 모드를 결정, 그에 맞는 매수·청산 기준을 적용한다.

    자본: 300만원 독립 운용. Sim1~7과 완전 분리.
    ML 레이블 수집: regime_log에 일별 국면·성과를 기록 (데이터 충분 시 ML 전환 예정).
    """

    MAX_HOLDINGS = 3

    # 국면별 파라미터
    REGIME_PARAMS = {
        "BULL": {
            "trailing_activation": 5.0,   # 이 수익률 이상이면 트레일링 스탑 활성
            "trailing_callback":   5.0,   # 고점 대비 이 % 하락 시 청산
            "hard_stop":          -8.0,   # 무조건 손절선
            "target_profit":       None,  # 고정 익절 없음 (트레일링 라이딩)
            "min_change_rate":     2.0,   # 당일 상승률 최소 (%)
            "max_change_rate":    30.0,
            "require_foreign":    True,   # 외인 순매수 조건
            "time_stop_days":     None,   # 타임 스탑 없음
        },
        "SIDEWAYS": {
            "trailing_activation": 3.0,
            "trailing_callback":   2.0,
            "hard_stop":          -5.0,
            "target_profit":       4.0,   # +4% 빠른 익절
            "min_change_rate":     0.5,
            "max_change_rate":     7.0,
            "require_foreign":    False,
            "time_stop_days":      7,
        },
        "BEAR": {
            "trailing_activation": 2.0,
            "trailing_callback":   1.5,
            "hard_stop":          -3.0,
            "target_profit":       2.5,   # +2.5% 빠른 탈출
            "min_change_rate":    -7.0,   # 하락 후 반등 노림
            "max_change_rate":    -0.5,
            "require_foreign":    False,
            "time_stop_days":      5,
        },
    }

    def __init__(self, initial_cash=3_000_000):
        super().__init__("orchestrator", initial_cash)

    # ── Sim0 상태 읽기 ─────────────────────────────────────────────
    def _read_regime(self) -> tuple[str, float]:
        """Sim0 리베로 state에서 국면과 bull_score를 읽는다. 실패 시 SIDEWAYS/50 반환."""
        try:
            path = os.path.join(self.data_dir, "sim_libero_state.json")
            with open(path, "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            regime = d.get("current_regime", "SIDEWAYS")
            bull_score = float(d.get("bull_score", 50.0))
            return regime if regime in self.REGIME_PARAMS else "SIDEWAYS", bull_score
        except Exception:
            return "SIDEWAYS", 50.0

    # ── 국면별 진입 필터 ───────────────────────────────────────────
    def _filter_candidates(self, candidates: list, params: dict) -> list:
        """국면 파라미터로 진입 후보를 필터링하고 우선순위 정렬."""
        out = []
        for s in candidates:
            code = s.get("code")
            if not code:
                continue
            if code in self.state.get("cooldown_codes", {}):
                continue

            price = float(s.get("price", 0) or 0)
            if price <= 0:
                continue

            amount = float(s.get("amount", 0) or 0)
            if amount < 5_000_000_000:  # 50억 이상 유동성
                continue

            cr = self.parse_change_rate(s)
            if not (params["min_change_rate"] <= cr <= params["max_change_rate"]):
                continue

            if params["require_foreign"]:
                foreign = float(s.get("foreign_change", 0) or 0)
                if foreign < 0:
                    continue

            sparkline = s.get("sparkline_price", []) or []
            if len(sparkline) >= 5:
                # 5일 추세 확인 (BULL: 우상향, BEAR: 하락 후 반등)
                trend_ok = sparkline[-1] > sparkline[0] if params["min_change_rate"] >= 0 else True
                if not trend_ok:
                    continue

            out.append((s, abs(cr)))  # (종목, 등락률 절댓값) — 절댓값 큰 순 정렬

        out.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in out]

    # ── 청산 로직 ─────────────────────────────────────────────────
    def _process_sells(self, current_prices: dict, params: dict) -> set:
        sold = set()
        today = get_kst_now().date()

        for code in list(self.state["portfolio"].keys()):
            pos = self.state["portfolio"].get(code)
            if not pos:
                continue
            cur = current_prices.get(code, 0)
            if cur <= 0:
                continue
            avg = pos.get("avg_price", 0)
            if avg <= 0:
                continue

            profit_rate = (cur - avg) / avg * 100

            # 하드 손절
            if profit_rate <= params["hard_stop"]:
                self.sell(code, cur,
                          reason=f"[Sim10] 손절 {profit_rate:.1f}% (기준 {params['hard_stop']}%)")
                self.add_cooldown(code, 3)
                sold.add(code)
                continue

            # 고정 익절 (SIDEWAYS/BEAR)
            if params["target_profit"] and profit_rate >= params["target_profit"]:
                self.sell(code, cur,
                          reason=f"[Sim10] 목표 익절 +{profit_rate:.1f}%")
                self.add_cooldown(code, 2)
                sold.add(code)
                continue

            # 트레일링 스탑
            if self.check_trailing_stop(code, cur,
                                        activation_pct=params["trailing_activation"],
                                        callback_pct=params["trailing_callback"]):
                self.sell(code, cur, reason=f"[Sim10] 트레일링 스탑 익절")
                sold.add(code)
                continue

            # 타임 스탑
            if params["time_stop_days"]:
                entry_str = pos.get("entry_date")
                if entry_str:
                    try:
                        entry_d = datetime.strptime(entry_str, "%Y-%m-%d").date()
                        if (today - entry_d).days >= params["time_stop_days"]:
                            self.sell(code, cur,
                                      reason=f"[Sim10] 타임 스탑 ({params['time_stop_days']}일)")
                            self.add_cooldown(code, 1)
                            sold.add(code)
                            continue
                    except ValueError:
                        pass

        return sold

    # ── 레짐 로그 기록 (ML 학습 데이터 축적용) ────────────────────
    def _log_regime(self, regime: str, bull_score: float):
        today_str = get_kst_now().strftime("%Y-%m-%d")
        log = self.state.setdefault("regime_log", [])

        if log and log[-1].get("date") == today_str:
            return  # 오늘 이미 기록됨

        nav = self.state["cash"] + self.state.get("invested", 0)
        log.append({
            "date": today_str,
            "regime": regime,
            "bull_score": round(bull_score, 1),
            "nav": nav,
            "holdings": len(self.state.get("portfolio", {})),
        })
        # 최근 200일만 보관
        if len(log) > 200:
            self.state["regime_log"] = log[-200:]

    # ── 메인 run() ────────────────────────────────────────────────
    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        regime, bull_score = self._read_regime()
        params = self.REGIME_PARAMS[regime]

        self.update_peak_prices(current_prices)

        # Sim0 국면 정보를 state에 기록
        self.state["active_regime"] = regime
        self.state["active_bull_score"] = round(bull_score, 1)

        # 청산
        self._process_sells(current_prices, params)

        # 매수 (BEAR 모드는 슬롯 1개로 제한)
        max_h = 1 if regime == "BEAR" else self.MAX_HOLDINGS
        slots = max_h - len(self.state["portfolio"])

        if slots > 0:
            picks = self._filter_candidates(candidates, params)[:slots]
            weight = 1.0 / max_h
            for s in picks:
                code = s.get("code")
                name = s.get("name", code)
                price = float(s.get("price", 0) or 0)
                if price <= 0:
                    continue
                if code in self.state["portfolio"]:
                    continue
                qty = int(self.state["cash"] * weight / price)
                if qty <= 0:
                    continue
                self.buy(code, name, price, qty,
                         reason=f"[Sim10-{regime}] bull={bull_score:.0f} weight={weight:.0%}")

        self._log_regime(regime, bull_score)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
