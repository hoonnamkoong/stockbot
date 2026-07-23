import json
import os

from .base_simulator import BaseSimulator, get_kst_now
from .sim4_bull_daytrading import decide_bull_daytrade
from .sim5_sideways_swing import decide_sideways
from .sim6_bear_hedge import decide_sim6, INVERSE_UNIVERSE


class Sim10OrchestratorSimulator(BaseSimulator):
    """[Sim 10] 메타-얼로케이터 — Sim0 국면에 따라 검증된 하위 전략 로직을 자기 자본으로 실행.

    BULL → Sim4-1(단타), SIDEWAYS → Sim5(눌림목), BEAR → Sim6(인버스 ETF 추세추종).
    자체 종목 선정을 하지 않는다. 300만원 독립 운용.
    """

    def __init__(self, initial_cash=3_000_000):
        super().__init__("orchestrator", initial_cash)

    def _read_regime(self):
        try:
            with open(os.path.join(self.data_dir, "sim_libero_state.json"), "r", encoding="utf-8-sig") as f:
                d = json.load(f)
            regime = d.get("current_regime", "SIDEWAYS")
            return regime if regime in ("BULL", "SIDEWAYS", "BEAR") else "SIDEWAYS", float(d.get("bull_score", 50.0))
        except Exception:
            return "SIDEWAYS", 50.0

    def get_universe(self):
        """국면 연동 유니버스. BULL=KIS 등락률 상위 30, BEAR=인버스 ETF 고정, SIDEWAYS=공통 버즈."""
        regime, _ = self._read_regime()
        if regime == "BULL":
            try:
                from src.trade.kis_data_provider import KISDataProvider
                return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
            except Exception:
                return None
        if regime == "BEAR":
            return [dict(e) for e in INVERSE_UNIVERSE]
        return None

    def _log_regime(self, regime, bull_score):
        today_str = get_kst_now().strftime("%Y-%m-%d")
        log = self.state.setdefault("regime_log", [])
        if log and log[-1].get("date") == today_str:
            return
        nav = self.state["cash"] + self.state.get("invested", 0)
        log.append({"date": today_str, "regime": regime, "bull_score": round(bull_score, 1),
                    "nav": nav, "holdings": len(self.state.get("portfolio", {}))})
        if len(log) > 200:
            self.state["regime_log"] = log[-200:]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        regime, bull_score = self._read_regime()
        self.update_peak_prices(current_prices)
        self.state["active_regime"] = regime
        self.state["active_bull_score"] = round(bull_score, 1)

        if regime == "BULL":
            orders = decide_bull_daytrade(self._view(current_prices), candidates, current_prices)
        elif regime == "SIDEWAYS":
            orders = decide_sideways(self._view(current_prices), candidates, current_prices)
        else:  # BEAR: 인버스 ETF 추세추종 + 직전 국면 잔여 보유 청산
            orders = decide_sim6(self._view(current_prices), candidates, current_prices)
            inverse_codes = {e['code'] for e in INVERSE_UNIVERSE}
            for code in list(self.state["portfolio"].keys()):
                if code in inverse_codes:
                    continue
                px = current_prices.get(code, 0)
                if px > 0 and not any(o['code'] == code for o in orders):
                    orders.append({'action': 'SELL', 'code': code, 'price': px, 'quantity': None,
                                   'reason': "[Sim10-BEAR] 국면전환 잔여 청산", 'cooldown': 1, 'mark_partial': False})

        self._apply(orders, current_prices)
        self._log_regime(regime, bull_score)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
