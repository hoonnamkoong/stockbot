from ..regime_state import read_regime, read_regime6_confirmed
from .base_simulator import BaseSimulator, get_kst_now, DEFAULT_INITIAL_CASH
from .sim4_bull_daytrading import decide_bull_daytrade
from .sim5_sideways_swing import decide_sideways, entry_allowed


def decide_bear_cash(view, current_prices):
    """[Sim10-BEAR] 현금 대기. 신규 BUY 없음, 보유분 전량 SELL. 순수 함수.

    2026-10-01 결정(docs/superpowers/specs/2026-10-01-sim6-bear-redesign.md §4·§5):
    t−1 BEAR 조건부 다음 날 코스피 기댓값은 사실상 0이고, 지금까지의 인버스 위임
    (decide_sim6)은 BEAR 슬롯에서 −43~−67%(복리 기여)였다. 가격이 없는 종목은
    팔지 않는다 — 지어낸 가격으로 팔지 않고 다음 사이클을 기다린다.
    """
    return [{'action': 'SELL', 'code': code, 'price': current_prices.get(code, 0),
             'quantity': None, 'reason': "[Sim10-BEAR] 현금 대기 — 보유 청산",
             'cooldown': 1, 'mark_partial': False}
            for code in list(view['portfolio'].keys())
            if (current_prices.get(code, 0) or 0) > 0]


class Sim10OrchestratorSimulator(BaseSimulator):
    """[Sim 10] 메타-얼로케이터 — Sim0 국면에 따라 검증된 하위 전략 로직을 자기 자본으로 실행.

    BULL → Sim4-1(단타), SIDEWAYS → Sim5(눌림목), BEAR → 현금 대기(10-01, 인버스 위임 폐지).
    자체 종목 선정을 하지 않는다. 300만원 독립 운용.
    """

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("orchestrator", initial_cash)

    @classmethod
    def needs_buzz(cls, regime: str | None) -> bool:
        """이 심의 버즈(네이버 게시글) 필요 여부는 국면에 따라 바뀐다.

        BULL은 get_universe()가 KIS 자체 유니버스를 쓰므로 불필요. BEAR는 현금
        대기라 후보 자체를 보지 않는다(보유 종목 가격은 보유분 보강 경로가 채운다).
        SIDEWAYS는 get_universe()가 None을 반환해 공통 버즈 후보로 폴백하므로
        필요. 국면을 모르면(regime=None) 버즈 필요로 취급한다 — 스크래핑을
        건너뛰었다가 실제로는 SIDEWAYS라 유니버스가 텅 비는 사고를 막는다.
        registry.needs_buzz()가 매니페스트의 needs_buzz: dynamic일 때 호출한다.
        """
        return regime not in ("BULL", "BEAR")

    def _read_regime(self):
        """Sim0(리베로)의 국면과 bull_score를 읽는다.

        판단할 수 없으면 (None, None)이다. 실패를 SIDEWAYS로 뭉개면 근거 없는
        국면으로 눌림목 전략이 실제로 돌아 신규 진입까지 나가고, 그 값이
        state["active_regime"]에 박혀 실거래 턴의 손익 귀속 태그까지 오염된다
        (program_trader._resolve_active_tag가 이 값을 읽는다).

        국면을 알면 bull_score만 빠진 경우는 50.0으로 채운다 — 하위 전략 선택은
        국면이 하고, 여기서 bull_score는 기록용(regime_log)이라 매매를 바꾸지 않는다.
        """
        regime, bull_score = read_regime(self.data_dir)
        if regime is None:
            return None, None
        return regime, 50.0 if bull_score is None else bull_score

    def get_universe(self):
        """국면 연동 유니버스. BULL=등락률 상위 30, BEAR=빈 목록(현금 대기 — 살 게
        없다), SIDEWAYS=시총 상위 100(중립).

        SIDEWAYS는 `decide_sideways`(심5의 판단 함수)를 그대로 쓴다. 그래서
        심5와 **같은 유니버스 문제를 그대로 물려받았다** — 버즈 후보로는
        "박스권 저점"이 한 종목도 들어오지 않는다(2026-08-14 실측: 저점에 가장
        가까운 종목조차 저점 대비 +24%, 기준은 +3%).

        심5와 같은 중립 풀을 쓴다. 조회 실패는 None이다 — 빈 리스트면 '후보
        없음'이 되어 그 국면 동안 아무것도 안 한다.
        """
        regime, _ = self._read_regime()
        if regime == "BULL":
            try:
                from src.trade.kis_data_provider import KISDataProvider
                return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
            except Exception:
                return None
        if regime == "BEAR":
            return []
        try:
            from src.data.market_cap_universe import fetch_top100
            return fetch_top100(limit=100)
        except Exception:
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
        if regime is None:
            # 판단 불가 — 하위 전략을 돌리지 않고 다음 사이클을 기다린다.
            # active_regime도 덮어쓰지 않는다: 지어낸 국면에 손익이 귀속된다.
            self.save_state(current_prices)
            return self.calculate_stats(current_prices)
        self.state["active_regime"] = regime
        self.state["active_bull_score"] = round(bull_score, 1)

        if regime == "BULL":
            orders = decide_bull_daytrade(self._view(current_prices), candidates, current_prices)
        elif regime == "SIDEWAYS":
            # 3단계 SIDEWAYS 안에도 강한횡보가 있다 — 심5와 같은 6단계 진입 게이트를 건다
            # (10-01 결정). 전일 확정값이라 심5·Sim14와 같다. 판정 불가면 진입 없음, 청산은 항상.
            # 페이퍼·실전(program_trader)이 같은 run()·같은 self.data_dir을 읽는다.
            orders = decide_sideways(self._view(current_prices), candidates, current_prices,
                                     allow_entry=entry_allowed(read_regime6_confirmed(self.data_dir)))
        else:  # BEAR: 현금 대기 — 신규 진입 없음, 보유분(구 인버스 포함) 전량 청산
            orders = decide_bear_cash(self._view(current_prices), current_prices)

        self._apply(orders, current_prices)
        self._log_regime(regime, bull_score)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
