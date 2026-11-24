from ..regime_state import read_regime, read_regime6_confirmed, to_regime3
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
    """[Sim 10] 메타-얼로케이터 — 리베로 국면에 따라 검증된 하위 전략 로직을 자기 자본으로 실행.

    라우팅 축은 **전일 확정 6단계 하나**다(2026-11-24 사용자 결정 A안):

        상승·매우상승 → Sim4-1(단타)
        하락·매우하락 → Sim5(눌림목)        ← 심5 진입 게이트가 열리는 국면
        약한횡보·강한횡보 → 현금 대기

    자체 종목 선정을 하지 않는다. 300만원 독립 운용.

    **왜 한 축인가.** 2026-11-24까지는 슬롯을 **오늘의 3단계**로 골랐다. 그런데
    SIDEWAYS 슬롯이 부르는 `decide_sideways`의 진입 게이트는 전일 확정 6단계가
    하락·매우하락일 때만 열리고(심5 `ALLOWED_REGIMES6`), 그 6단계는 3단계로
    BEAR다 — 그리고 3단계 BEAR는 현금 슬롯이었다. 전략이 든 슬롯과 그 전략이
    허용되는 국면이 **배타적**이었다. 그래서 약한횡보가 허용 집합에서 빠진
    `5cabc3aa2`(2026-10-02) 이후 눌림목 진입이 0건이고, 마지막 매수가 그 커밋과
    같은 날이다. 11-23에 국면 writer가 복구되어(PR #148) 게이트가 열린 그날,
    심5는 같은 함수로 5종목을 샀고 이 심은 0종목이었다 — 게이트가 열렸기
    때문에 못 샀다. 라우팅을 게이트와 같은 값에서 파생시키면 이 어긋남이
    구조적으로 불가능해진다(tests/test_sim10_regime_gate.py의 불변식).
    """

    def __init__(self, initial_cash=DEFAULT_INITIAL_CASH):
        super().__init__("orchestrator", initial_cash)

    @classmethod
    def needs_buzz(cls, regime: str | None) -> bool:
        """이 심을 어느 워크플로가 돌리는가 — 버즈 불필요면 trading.yml(60초 루프),
        필요하면 scraper.yml(스크래핑 직후). registry.needs_buzz()가 매니페스트의
        `needs_buzz: dynamic`일 때 호출한다. **인자는 3단계 국면이다.**

        ⚠ 라우팅 축이 6단계로 바뀐 뒤(2026-11-24) 이 값은 **보수적으로 남겨둔
        것**이다. 세 슬롯 모두 get_universe()가 자체 유니버스를 주므로 버즈가
        실제로 필요한 경우는 없다 — 눌림목 슬롯이 쓰는 `range_history`도
        `trade_engine._enrich_universe`가 채운다. 그래도 True를 돌려주는 국면을
        남긴 이유는 소유권을 옮기는 변경이 조용히 깨지는 부류이고(워크플로 간
        소유권 규칙), 이번 수정에 **필요하지 않기** 때문이다. 버즈는 수확되지만
        쓰이지 않는다. 정리하려면 매니페스트를 `needs_buzz: false`로 바꾸고 이
        classmethod를 지우는 별도 작업이다.
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
        """슬롯 연동 유니버스. **run()과 같은 축(전일 확정 6단계)으로 고른다.**

        상승계 = 등락률 상위 30(단타), 하락계 = 시총 상위 100(눌림목 — 심5와
        같은 중립 풀), 횡보계 = 빈 목록(현금 대기).

        축을 반드시 run()과 맞춰야 한다. 3단계로 고르면 하락계(=3단계 BEAR)에서
        빈 목록이 나오는데, 호출부는 `if not own_universe: return candidates`라
        **빈 목록이 '후보 없음'이 아니라 '파이프라인(버즈) 후보로 폴백'**이다.
        그러면 눌림목이 버즈 풀을 먹는다 — 거기엔 "박스권 저점"이 한 종목도
        없다(2026-08-14 실측: 저점에 가장 가까운 종목조차 저점 대비 +24%,
        기준은 +3%). 라우팅만 고치고 여기를 두면 수정이 무효가 된다.

        횡보계의 빈 목록도 같은 이유로 파이프라인 후보로 폴백되지만, 현금 슬롯은
        후보를 보지 않으므로 무해하다. 판정 불가·조회 실패는 None이다.
        """
        regime6 = read_regime6_confirmed(self.data_dir)
        if regime6 is None:
            return None
        if to_regime3(regime6) == "BULL":
            try:
                from src.trade.kis_data_provider import KISDataProvider
                return KISDataProvider().get_fluctuation_rank(market='0001', sort='0', limit=30)
            except Exception:
                return None
        if entry_allowed(regime6):
            try:
                from src.data.market_cap_universe import fetch_top100
                return fetch_top100(limit=100)
            except Exception:
                return None
        return []

    def _log_regime(self, regime, bull_score, regime6, slot):
        """하루 한 행. **regime6·slot을 같이 남긴다** — 2026-11-24 조사에서 이 로그에
        3단계와 bull_score만 있어 "어느 슬롯이 돌았는가"를 코드로 재구성해야 했다.
        그 사이 53일간 매수 0건의 이유가 로그 어디에도 없었다."""
        today_str = get_kst_now().strftime("%Y-%m-%d")
        log = self.state.setdefault("regime_log", [])
        if log and log[-1].get("date") == today_str:
            return
        nav = self.state["cash"] + self.state.get("invested", 0)
        log.append({"date": today_str, "regime": regime, "bull_score": round(bull_score, 1),
                    "regime6": regime6, "slot": slot,
                    "nav": nav, "holdings": len(self.state.get("portfolio", {}))})
        if len(log) > 200:
            self.state["regime_log"] = log[-200:]

    def run(self, candidates, current_prices=None):
        current_prices = current_prices or {}
        regime, bull_score = self._read_regime()
        # 라우팅 축. 전일 확정값이라 심5·Sim14와 같고 룩어헤드가 없다. 장중
        # `regime6`는 안 본다(10시 이후 오늘 판정이 섞여 백테스트와 다른 게이트가 된다).
        regime6 = read_regime6_confirmed(self.data_dir)
        self.update_peak_prices(current_prices)
        if regime is None or regime6 is None:
            # 판단 불가 — 하위 전략을 돌리지 않고 다음 사이클을 기다린다.
            # 귀속 태그(active_regime·active_slot)도 덮어쓰지 않는다: 지어낸
            # 국면에 손익이 붙는다.
            self.save_state(current_prices)
            return self.calculate_stats(current_prices)
        # 3단계·bull_score는 라우팅에서 빠졌지만 대시보드·리포트가 읽으므로 계속 남긴다.
        self.state["active_regime"] = regime
        self.state["active_bull_score"] = round(bull_score, 1)

        if to_regime3(regime6) == "BULL":
            slot = "daytrade"
            orders = decide_bull_daytrade(self._view(current_prices), candidates, current_prices)
        elif entry_allowed(regime6):
            # **이 분기 조건이 곧 심5의 진입 게이트다.** 그래서 allow_entry는 여기서
            # 항상 True다 — 눌림목을 '살 수 없는 상태'로 돌리는 경우가 없어진다.
            # 소유자는 심5(ALLOWED_REGIMES6)이고, 심5가 허용 집합을 바꾸면 이
            # 라우팅이 따라 움직인다. 청산은 국면과 무관하게 항상 나간다.
            slot = "sideways"
            orders = decide_sideways(self._view(current_prices), candidates, current_prices,
                                     allow_entry=True)
        else:  # 횡보계: 현금 대기 — 신규 진입 없음, 보유분 전량 청산(10-01 결정을 이 축으로)
            slot = "cash"
            orders = decide_bear_cash(self._view(current_prices), current_prices)
        # 원장 귀속 태그는 이 값을 읽는다(program_trader._resolve_active_tag).
        self.state["active_slot"] = slot

        self._apply(orders, current_prices)
        self._log_regime(regime, bull_score, regime6, slot)
        self.save_state(current_prices)
        return self.calculate_stats(current_prices)
