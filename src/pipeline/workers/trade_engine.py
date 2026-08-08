"""
[V50.1] Stage 3 Worker: 전략 판단 + 시뮬레이터 (TradeEngineWorker)
=======================================================
실제 engine.py / simulator 인터페이스에 맞게 수정.
- engine.execute_simulation(candidates, allow_buy) 사용
- sim.run(candidates_list, current_prices=dict) 사용
"""

import os
import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData, SyncState
from src.data.storage_manager import StorageManager
from src.strategy.registry import get_active_simulators


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs); n = len(s); m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0


def breadth_from_csv_text(text: str, expected_date: str) -> float | None:
    """KOSPI top100 CSV 텍스트(행: 'YYYYMMDD,종가,종가,...')의 최근 2행으로
    전일 대비 상승 종목 비율(%)을 산출한다.

    마지막 행 날짜가 expected_date(YYYYMMDD)와 다르면 CSV가 아직 오늘 종가를
    반영하지 못한 것(stale) → None을 반환한다. 얼어붙은 값을 정답으로 기록하면
    채점(calibration)이 오염되므로, '측정 불가'는 0/이전값이 아니라 None이다."""
    lines = [l for l in text.split('\n') if l.strip()]
    if len(lines) < 3:  # 헤더 + 데이터 최소 2행
        return None
    prev_cols = lines[-2].split(',')
    curr_cols = lines[-1].split(',')
    if curr_cols[0].strip() != str(expected_date):
        return None  # stale: 오늘 종가 미반영 → 정답 없음
    ups, total = 0, 0
    for p_str, c_str in zip(prev_cols[1:], curr_cols[1:]):
        try:
            p, c = float(p_str.strip()), float(c_str.strip())
            if p > 0:
                total += 1
                if c > p:
                    ups += 1
        except ValueError:
            continue
    return round(ups / total * 100, 1) if total > 0 else None


def _adx(series):
    if len(series) < 2:
        return 0.0
    direction = abs(series[-1] - series[0])
    volatility = sum(abs(series[i] - series[i - 1]) for i in range(1, len(series)))
    return (direction / volatility * 100.0) if volatility else 0.0


def libero_action(after_close: bool, market_hours: bool) -> str | None:
    """리베로가 이번 런에서 할 일.

    15:30~15:49는 두 조건이 함께 참이다. 마감 후 확정을 먼저 판정하지 않으면
    EOD 채점이 영영 돌지 않는다 (태스커의 마지막 신호가 15:30이기 때문).
    """
    if after_close:
        return 'finalize'
    if market_hours:
        return 'nowcast'
    return None


class TradeEngineWorker(BaseWorker):
    """
    Stage 3: 전략 판단(BUY/WATCH) + 시뮬레이터 주가 동기화.
    StrategyEngine.execute_simulation()을 통해 전략을 실행합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self._kis_provider = None  # 백필용 KISDataProvider 지연 생성

    def run(
        self,
        stocks: list[StockData],
        sync_state: SyncState,
        skip_program_trading: bool = False,
        paper_owned_elsewhere: str | None = None,
    ) -> tuple[list, list, dict]:
        """
        전략 판단과 딥다이브 대상 선정을 수행합니다.

        skip_program_trading: 이번 사이클의 실전 주문을 다른 워크플로(trading.yml)가
        낸다면 True. 원장 락·중복가드가 막아주긴 하지만, 불필요한 GitHub API
        왕복을 아예 피한다.

        paper_owned_elsewhere: 그 심의 **페이퍼 쌍둥이도** trading.yml이 갱신·배포
        한다는 뜻이다. 여기서 같은 심을 런 시작 시점 스냅샷으로 다시 돌리면
        그 사이(4~5분) 페이퍼 매매가 되돌아간다 — 파일당 writer는 하나여야 한다.

        Returns:
            (final_picks, simulation_results, sell_candidate)
        """
        # 신규 버즈 종목이 없어도 계속 간다. 여기서 빠져나가면 전 페이퍼 심이 그
        # 사이클을 통째로 건너뛰고(보유 종목 손절·익절도 안 된다), 버즈 필요 심이
        # 실전이면 **그 사이클의 실전 매매도 사라진다** — 그 경로의 주문 주체는
        # Stage 3 하나뿐이다. orchestrator Stage 2가 "신규 종목 없어도 Stage 3을
        # 실행하려고" 빈 리스트로 넘겨주는 것도 같은 이유다.
        #
        # 후보가 비어도 안전하다: 심은 현재가 없는 종목을 이미 걸러내고
        # (`if cur <= 0: continue`), 보유 종목 가격은 _run_simulators의 네이버
        # 보강이 채운다.
        candidates = [s.to_dict() for s in stocks]

        # 1. StrategyEngine으로 전략 판단
        try:
            from src.strategy.engine import StrategyEngine
            engine = StrategyEngine()
            # 신규 매수는 정규장 종료(15:30)에 멈춘다. is_market_hours()의 상한은
            # 15:50이라 그걸 쓰면 체결 불가(또는 익일 이월) 매수가 나간다.
            # 프로그램 매매도 같은 차단선을 쓴다 — 갈리면 페이퍼와 실전이 어긋난다.
            allow_buy = self.ctx.is_buy_window()
            simulation_results = engine.execute_simulation(candidates, allow_buy=allow_buy)
            self.log(f"전략 판단 완료: {len(simulation_results)}개 / allow_buy={allow_buy}")
        except Exception as e:
            self.log_error(f"StrategyEngine 실패: {e}")
            # Fallback: 모든 종목을 WATCH로
            simulation_results = [
                {'code': s.code, 'name': s.name, 'signal': 'WATCH', 'reason': 'Engine fallback'}
                for s in stocks
            ]

        # 2. signal 정보를 원본 candidates에 병합
        signal_map = {r['code']: r.get('signal', 'WATCH') for r in simulation_results}
        for c in candidates:
            c['signal'] = signal_map.get(c['code'], 'WATCH')

        # 3. 중복 방지: 당일 이미 딥다이브가 나간 종목 제외
        deep_dived = sync_state.daily_deep_dive_codes
        new_picks = []

        # BUY/WATCH 시그널 중 오늘 딥다이브 안 나간 것 상위 2개 추출
        for r in simulation_results:
            if r.get('signal') in ['BUY', 'WATCH'] and r['code'] not in deep_dived:
                # candidates에서 풀 데이터 가져오기
                full = next((c for c in candidates if c['code'] == r['code']), r).copy()
                full['signal'] = r.get('signal', 'WATCH')
                new_picks.append(full)
                if len(new_picks) >= 2:
                    break

        final_picks = new_picks[:2]
        # 해당 배치 내 순위(rank) 추가: 1~2위
        for i, p in enumerate(final_picks):
            p['rank'] = i + 1

        # 4. 실전 계좌 매도 후보 선정 (정각 텔레그램 타이밍에만)
        sell_candidate = None
        if self.ctx.should_notify():
            try:
                from src.strategy.advisor import StrategyAdvisor
                from src.trade.balance import get_balance
                advisor = StrategyAdvisor()
                balance = get_balance()
                if not balance.get('error'):
                    holdings = balance.get('holdings', [])
                    # 보유 종목 중 오늘 딥다이브 안 나간 것만 대상으로 선정
                    potential_sells = [h for h in holdings if h['code'] not in deep_dived]
                    sell_candidate = advisor.select_sell_candidate(potential_sells)
                    if sell_candidate:
                        self.log(f"매도 추천 후보 선정: {sell_candidate['name']}")
            except Exception as e:
                self.log_error(f"매도 후보 선정 실패: {e}")

        # 5. 신규 보고 종목 상태 기록 - 정각 텔레그램 타이밍에만 수행
        hour = self.ctx.now_kst.hour
        is_morning = hour < 12
        session_name = "오전" if is_morning else "오후"

        if (final_picks or sell_candidate) and self.ctx.should_notify():
            self.log(f"[{session_name} 세션] 신규 보고 대상 상태 기록 (Deep-Dive)")
            
            # 딥다이브 중복 방지 리스트에 추가
            for p in final_picks:
                if p['code'] not in sync_state.daily_deep_dive_codes:
                    sync_state.daily_deep_dive_codes.append(p['code'])
            if sell_candidate and sell_candidate['code'] not in sync_state.daily_deep_dive_codes:
                sync_state.daily_deep_dive_codes.append(sell_candidate['code'])
            
            # 세션별 일반 보고 리스트에도 추가 (기존 대시보드 호환)
            new_items = [{'code': p['code'], 'name': p['name'], 'rank': p.get('rank', 0)} for p in final_picks]
            if is_morning:
                sync_state.morning_reported_info.extend(new_items)
            else:
                sync_state.afternoon_reported_info.extend(new_items)
            
            sync_state.daily_reported_info.extend(new_items)

            # 세션 완료 여부 (9개 기준)
            total_session = len(sync_state.morning_reported_info if is_morning else sync_state.afternoon_reported_info)
            if is_morning:
                sync_state.morning_complete = total_session >= 9
            else:
                sync_state.afternoon_complete = total_session >= 9
            
            self.storage.save_sync_state(sync_state)
        elif final_picks or sell_candidate:
            self.log(f"[{session_name} 세션] 정각 아님 - 종목 상태 기록 생략")

        # 6. 시뮬레이터 실행 (Registry에서 자동 로드; sim0_libero는 run_regime_stage()가 별도로 돔)
        self._run_simulators(candidates, exclude_sim_id=paper_owned_elsewhere)

        # 7. 프로그램 매매(실전 계좌 자동 심 운용) — config ON & 유효 시에만 실주문(내부 fail-closed)
        # 버즈 불필요 심은 orchestrator가 Stage 1 이전에 이미 실행했다(skip_program_trading=True).
        if not skip_program_trading:
            try:
                from src.pipeline.workers.program_trader import run_program_trading
                run_program_trading(
                    candidates,
                    is_market_hours=self.ctx.is_market_hours(),
                    now_kst=self.ctx.now_kst,
                    log=self.log,
                    log_error=self.log_error,
                    enrich=self._enrich_universe,  # 심 전용 유니버스 보강 — 페이퍼 경로와 동일 적용
                )
            except Exception as e:
                self.log_error(f"프로그램 매매 실행 실패(무시하고 계속): {e}")

        return final_picks, simulation_results, sell_candidate

    def run_regime_stage(self) -> str | None:
        """Sim0(리베로) 국면 갱신 — 스크래핑 전에 사이클당 정확히 한 번 돈다(E3).

        top100 라이브 실측만으로 국면을 계산한다(E2: candidates=[]로 호출해도
        breadth/momentum/trend는 산출된다). Sim10의 순서 가변 라우팅
        (needs_buzz=dynamic)이 이 결과를 읽으므로, 스크래핑 전에 매매를
        내보내려면 스크래핑 전에 국면도 갱신돼 있어야 한다.

        사이클당 한 번만 불러야 한다 — regime_history가 호출마다 누적되므로
        두 번 부르면 국면 평활(smoothing)이 같은 순간을 두 번 반영해 왜곡된다.

        같은 이유로 **호출 주기를 바꾸는 것은 알고리즘을 바꾸는 것이다.**
        국면은 최근 5회 관측의 과반으로 확정되므로(sim0_libero._confirm_regime),
        주기가 곧 평활 시간상수다: 10분 주기면 50분치, 1분 주기면 5분치가 된다.
        더 자주 부르려면 history 창 크기(현재 5)도 함께 키워야 하고, 그건 별도
        검증이 필요한 변경이다.

        비용은 제약이 아니다 — 라이브 경로(_fetch_top100_breadth)는 네이버 시총
        페이지 최대 4장이고 실측 3.7초다. "종목당 1콜 ~100콜"은 런 결측을 사후
        복원하는 _backfill_breadth_kis의 비용이지 이 경로가 아니다.
        _run_simulators()는 그래서 분석기 심(IS_ANALYZER)을 건너뛴다 — 여기가
        유일한 실행 지점이다.

        반환: 확정 국면(current_regime) 문자열, 또는 판단 불가 시 None.
        """
        live_breadth = None  # (breadth%, momentum, 표본수, [codes]) | None
        try:
            live_breadth = self._fetch_top100_breadth()
            if live_breadth:
                self.log(f"  top100 라이브 breadth: {live_breadth[0]:.1f}% (표본 {live_breadth[2]})")
        except Exception as e:
            self.log_error(f"top100 라이브 breadth 수집 실패: {e}")

        from src.strategy.registry import get_analyzer_simulator
        try:
            sim = get_analyzer_simulator()
        except Exception as e:
            self.log_error(f"분석기 심 로드 실패(국면 판단 스킵): {e}")
            return None

        sim.live_market_metrics = {
            'breadth': live_breadth[0], 'momentum': live_breadth[1],
            'trend': self._top100_trend_from_csv(),  # None이면 Sim0가 버즈 ADX로 폴백(candidates=[]라 0.0)
            'sample': live_breadth[2],
        } if live_breadth else None

        try:
            result = sim.run([], current_prices={})
        except Exception as e:
            self.log_error(f"{sim.__class__.__name__} 실행 실패: {e}")
            return None
        self.log(f"  {sim.__class__.__name__} 완료 (국면: {result.get('current_regime')})")

        # 리베로 나우캐스트: 장중엔 시간당 실측·예측·채점, 마감 후엔 EOD 확정 채점
        now_kst = self.ctx.now_kst
        action = libero_action(
            after_close=self.ctx.is_after_market_close(),
            market_hours=self.ctx.is_market_hours(),
        )
        try:
            if action == 'finalize':
                # 마감 후 라이브 등락률 = 확정 종가 기준. 실패 시 당일 갱신 CSV 폴백.
                actual_eod = live_breadth[0] if live_breadth else self._get_actual_breadth_from_csv()
                sim.finalize_eod(actual_eod, now_kst=now_kst)
                self._append_regime_observation(now_kst, live_breadth)
            elif action == 'nowcast' and live_breadth:
                codes = live_breadth[3]
                sim.update_nowcast(
                    live_breadth[0], now_kst=now_kst,
                    backfill=lambda hhmm: self._backfill_breadth_kis(hhmm, codes))
                self._append_regime_observation(now_kst, live_breadth)
        except Exception as e:
            self.log_error(f"리베로 나우캐스트 처리 실패(무시): {e}")

        return result.get('current_regime')

    def _run_simulators(self, candidates: list[dict], only_sim_id: str | None = None,
                        allow_price_fallback: bool = True,
                        universe_override: list[dict] | None = None,
                        exclude_sim_id: str | None = None) -> None:
        """
        YAML Manifest의 active 시뮬레이터들을 실행합니다.
        실제 simulator.run(candidates, current_prices=dict) 시그니처 사용.
        [Fix] 포트폴리오 보유 종목 중 오늘 Buzz Filter 이탈 종목의
              현재가를 네이버에서 별도 조회하여 current_prices에 보강합니다.

        분석기 심(sim0_libero)은 여기서 돌지 않는다 — run_regime_stage()가
        사이클당 한 번 별도로 돈다(E3).

        only_sim_id: 지정하면 그 심 하나만 돈다. trade_loop(60초 주기)가 실전 선택
          심의 페이퍼 쌍둥이만 갱신하는 데 쓴다 — 전 심을 2분마다 돌리면 런이
          153초로 120초 창을 넘겨 매 사이클이 겹친다(2026-08-06 실측).
        allow_price_fallback: False면 네이버 직접 조회(_fetch_portfolio_prices)를
          하지 않는다. lite 경로는 "스크래핑을 하지 않는다"가 전제라 이 폴백이 살아
          있으면 2분마다 네이버를 두드리게 된다. 가격을 못 구한 보유 종목이 있는
          심은 이번 사이클을 건너뛴다 — 0으로 폴백해 허위 손절을 내지 않는다.
        exclude_sim_id: 그 심을 여기서 돌리지 않는다. trading.yml이 60초 루프로
          이미 돌리고 배포하는 심을 스크래퍼가 자기 스냅샷(런 시작 시점)에서 다시
          돌리면, data/*.json 통째 배포가 그 4~5분치 페이퍼 매매를 되돌린다
          (lost update). 파일당 writer는 하나여야 한다. 심의 신원은 클래스가
          아니라 **상태 파일**로 본다 — 같은 클래스의 변형이 여럿 있을 수 있다.
        universe_override: 프로그램 매매가 방금 확정한 유니버스를 그대로 쓴다
          (only_sim_id와 함께 쓴다). 이게 없으면 오프틱 사이클이 유니버스를 두 번
          만든다 — 실전 경로에서 한 번, 여기서 또 한 번. 부하가 두 배인 것보다
          파리티가 문제다: 두 조회는 수십 초 차이라 서로 다른 '당일 등락률 상위
          30'을 볼 수 있고, 그러면 실전과 그 페이퍼 쌍둥이가 다른 유니버스로
          판단한다.
        """
        try:
            # 1. 오늘 candidates 기반으로 현재가 구성
            current_prices = {
                s['code']: s.get('price', s.get('current_price', 0))
                for s in candidates if s.get('code')
            }
            if only_sim_id:
                # 인스턴스에는 매니페스트 id가 붙어 있지 않다. 이름으로 하나만 만든다.
                # initial_cash는 기본값(매니페스트의 심 자본)을 쓴다 — 페이퍼 쌍둥이는
                # 다른 심과 같은 조건이어야 비교가 성립한다(프로그램 예산이 아니다).
                from src.strategy.registry import get_simulator_by_id
                one = get_simulator_by_id(only_sim_id)
                if one is None:
                    self.log(f"시뮬레이터 동기화: '{only_sim_id}' 로드 실패 — 생략")
                    return
                simulators = [one]
            else:
                simulators = [s for s in get_active_simulators()
                              if not getattr(s, 'IS_ANALYZER', False)]
                skip_file = self._state_file_of(exclude_sim_id)
                if skip_file:
                    simulators = [s for s in simulators
                                  if os.path.basename(getattr(s, 'state_file', '')) != skip_file]
                    self.log(f"  '{exclude_sim_id}' 제외 — trading.yml이 그 심의 writer다")
            self.log(f"시뮬레이터 동기화 시작 ({len(simulators)}개 활성, {len(current_prices)}개 현재가)")

            # 2. 포트폴리오 종목 중 현재가 미확보된 코드 수집
            missing_codes = set()
            for sim in simulators:
                for code in sim.state.get('portfolio', {}).keys():
                    if code not in current_prices or current_prices[code] == 0:
                        missing_codes.add(code)

            # 3. 미확보 종목 현재가를 네이버에서 조회하여 보강
            if missing_codes and allow_price_fallback:
                self.log(f"  현재가 미확보 {len(missing_codes)}개 종목 네이버 보강 조회")
                extra = self._fetch_portfolio_prices(list(missing_codes))
                current_prices.update(extra)
                self.log(f"  보강 결과: { {k: v for k, v in extra.items()} }")
            elif missing_codes:
                self.log(f"  현재가 미확보 {len(missing_codes)}개 — 네이버 보강 생략"
                         f"(lite 경로). 자체 유니버스로 못 채우는 심은 건너뜁니다.")

            for sim in simulators:
                try:
                    # 일봉 전략은 장중 10분 루프에서 돌 이유가 없다 —
                    # scripts/run_eod_sims.py가 마감 후 1회 돌린다.
                    if getattr(sim, 'IS_EOD', False):
                        continue
                    # 넘겨받은 유니버스가 있으면 다시 만들지 않는다. 빈 리스트는
                    # '유니버스가 비었다'가 아니라 '넘겨받은 게 없다'로 읽는다 —
                    # 빈 유니버스로 돌리면 보유 종목 현재가가 통째로 사라져
                    # 허위 손절이 난다.
                    sim_candidates = universe_override or None
                    own_universe = None if sim_candidates else sim.get_universe()
                    if own_universe:
                        sim_candidates = self._enrich_universe(own_universe)
                    if sim_candidates:
                        sim_prices = dict(current_prices)
                        sim_prices.update({
                            s['code']: s.get('price', s.get('current_price', 0))
                            for s in sim_candidates if s.get('price', 0) > 0
                        })
                    else:
                        sim_candidates = candidates
                        sim_prices = current_prices

                    # 네이버 폴백을 끈 경로(lite)에서는 보유 종목 현재가가 비어 있을 수
                    # 있다. 0을 현재가로 넘기면 심이 −100% 손실로 읽고 허위 손절을 낸다.
                    # 모르는 값은 지어내지 않고 이번 사이클을 건너뛴다.
                    if not allow_price_fallback:
                        blind = [c for c in sim.state.get('portfolio', {})
                                 if not sim_prices.get(c)]
                        if blind:
                            self.log(f"  {sim.__class__.__name__} 건너뜀 — 보유 "
                                     f"{len(blind)}종목 현재가 측정 불가 {blind}")
                            continue

                    sim.run(sim_candidates, current_prices=sim_prices)
                    self.log(f"  {sim.__class__.__name__} 완료")
                except Exception as e:
                    self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")

            self.log("시뮬레이터 동기화 완료")
        except Exception as e:
            self.log_error(f"시뮬레이터 전체 실패: {e}")

    @staticmethod
    def _state_file_of(sim_id: str | None) -> str | None:
        """매니페스트가 그 심에 물려둔 상태 파일 이름. 못 찾으면 None.

        못 찾았다고 전 심을 돌리는 쪽으로 fail한다 — 제외에 실패해 한 번 겹치는
        것이 심을 통째로 빠뜨리는 것보다 낫다.
        """
        if not sim_id:
            return None
        try:
            from src.strategy.registry import get_sim_registry
            for s in get_sim_registry(include_analyzers=True):
                if s['id'] == sim_id:
                    return s['state_file']
        except Exception:
            pass
        return None

    def _enrich_universe(self, stocks: list[dict]) -> list[dict]:
        """
        sim.get_universe() 반환 종목에 sparkline + per/pbr 보강.
        DataFetcher를 거치지 않은 종목이므로 별도 enrichment 필요.
        """
        import re
        import requests
        from bs4 import BeautifulSoup
        from concurrent.futures import ThreadPoolExecutor

        def fetch_sparkline(stock):
            code = stock.get('code', '')
            if not code:
                return stock
            try:
                url = f"https://finance.naver.com/item/frgn.naver?code={code}"
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                soup = BeautifulSoup(res.content, 'html.parser')
                rows = soup.select('table.type2 tr')
                data_rows = [
                    r.select('td') for r in rows
                    if len(r.select('td')) == 9
                    and re.match(r'\d{4}', r.select('td')[0].get_text(strip=True))
                ]
                if data_rows:
                    # price/current_price는 get_universe()가 이미 KIS 라이브 값으로
                    # 채워왔다면 덮어쓰지 않는다 — 이 페이지(frgn.naver)는 일봉이라 장중에
                    # 전일 값에서 멈춰 있을 수 있다(Sim6가 6주간 거래 0건이던 원인과 동일
                    # 함정). 2026-08-04: 이 덮어쓰기가 Sim4-1의 라이브 판단가를 지워
                    # 실전 계좌가 하루 종일 매수 0건이었다(check_buy_drift가 계속 차단).
                    # 유니버스 자체에 price가 없을 때(Sim6 고정 리터럴)만 이 값을 쓴다.
                    if not stock.get('price'):
                        price_text = data_rows[0][1].get_text().replace(',', '').strip()
                        if price_text.isdigit():
                            stock['price'] = int(price_text)
                            stock['current_price'] = stock['price']
                    sparkline = []
                    for row in data_rows[:5]:
                        try:
                            sparkline.append(int(row[1].get_text().replace(',', '').strip()))
                        except Exception:
                            pass
                    if sparkline:
                        stock['sparkline_price'] = sparkline[::-1]  # 오래된→최신 순
                    if len(data_rows) >= 2:
                        stock['foreign_rate'] = float(
                            data_rows[0][8].get_text().replace('%', '').replace(',', '').strip() or 0
                        )
                        # [Sim8] foreign_change: info 축 세 항 중 하나. 이게 없으면 횡단면
                        # z가 퇴화해 info가 전 종목 비고 진입이 원천 차단된다.
                        # 같은 표의 어제 행이라 추가 콜 0.
                        prev_rate = float(
                            data_rows[1][8].get_text().replace('%', '').replace(',', '').strip() or 0
                        )
                        stock.setdefault('foreign_change',
                                         round(stock['foreign_rate'] - prev_rate, 3))
            except Exception:
                pass
            return stock

        with ThreadPoolExecutor(max_workers=10) as ex:
            enriched = list(ex.map(fetch_sparkline, stocks))

        # per/pbr/sector_name + 수급 보강 (Sim3 가치페어, Sim4/4-1 has_inst 조건용)
        # 종목당 최대 2콜(get_price_quote + get_investor_trend_estimate)을 순차로
        # 돌면 30종목에 수십 초가 든다 — sparkline과 같은 방식으로 병렬화한다.
        # kis 인스턴스를 스레드끼리 공유하는 이유는 스파크라인 단계와 같다: 그래야
        # get_price_quote의 인스턴스 캐시가(같은 종목이 중복 조회될 때) 의미가 있다.
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()

            def enrich_kis(stock):
                code = stock.get('code', '')
                if not code:
                    return stock
                # PER/PBR + 등락률 + 52주 고저
                if (not (stock.get('per') and stock.get('pbr'))
                        or 'change_rate' not in stock or 'w52_hgpr' not in stock):
                    try:
                        quote = kis.get_price_quote(code)
                        for k in ('per', 'pbr', 'sector_name'):
                            if quote.get(k):
                                stock[k] = quote[k]
                        # 고정 유니버스(코드+이름만 든 리터럴)는 등락률이 없어 심의
                        # '당일 상승' 조건이 영원히 거짓이 된다 — Sim6가 6주간 거래
                        # 0건이던 원인이다. 네이버 frgn 페이지는 일봉이라 장중에 전일
                        # 값이 박제될 수 있어, 실시간인 KIS 현재가(prdy_ctrt)를 쓴다.
                        # 조회 실패(price=0)를 0%로 채우면 '보합'이라는 거짓이 되므로
                        # 그때는 키를 붙이지 않는다.
                        if 'change_rate' not in stock and quote.get('price'):
                            rate = quote.get('change_rate_pct', 0.0)
                            stock['change_rate'] = f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%"
                        # [Sim8] 52주 고저 — 앵커 판정(_nearness)의 재료. 0으로 채우면
                        # 앵커가 0으로 나뉘므로, 값이 있을 때만 붙인다.
                        for _f in ('w52_hgpr', 'w52_lwpr'):
                            if _f not in stock and quote.get(_f):
                                stock[_f] = quote[_f]
                        # [Sim9] 갭소진 판정 재료. 자체 유니버스(등락률 상위)로 들어온
                        # 종목엔 이 필드들이 없어 갭 계산 전에 전량 continue됐다.
                        for _f in ('open_price', 'day_high', 'day_low', 'prev_close'):
                            if _f not in stock and quote.get(_f):
                                stock[_f] = quote[_f]
                    except Exception:
                        pass
                # 수급 — 유니버스 자체에 이미 값이 있으면 덮어쓰지 않음
                if 'frgn_fake_ntby_qty' not in stock or 'orgn_fake_ntby_qty' not in stock:
                    try:
                        trend = kis.get_investor_trend_estimate(code)
                        stock.setdefault('frgn_fake_ntby_qty', trend.get('frgn_fake_ntby_qty', 0))
                        stock.setdefault('orgn_fake_ntby_qty', trend.get('orgn_fake_ntby_qty', 0))
                    except Exception:
                        pass
                return stock

            with ThreadPoolExecutor(max_workers=10) as ex:
                enriched = list(ex.map(enrich_kis, enriched))
        except Exception:
            pass

        return enriched

    @staticmethod
    def _breadth_momentum(rates):
        """top100 등락률 리스트 → (breadth%, momentum median). 빈 리스트면 None."""
        if not rates:
            return None
        ups = sum(1 for r in rates if r > 0)
        return round(ups / len(rates) * 100, 1), round(_median(rates), 2)

    def _top100_trend_from_csv(self, csv_path='output/kospi_top100_close.csv', lookback=10):
        """종가 시계열 CSV(wide)에서 종목별 ADX 근사의 median. 실패 시 None."""
        import csv as _csv
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                rows = list(_csv.reader(f))
        except Exception:
            return None
        if len(rows) < 3:
            return None
        header = rows[0]
        data = rows[1:][-lookback:]
        adxs = []
        for col in range(1, len(header)):
            series = []
            for r in data:
                if col < len(r):
                    try:
                        series.append(float(r[col]))
                    except ValueError:
                        pass
            if len(series) >= 2:
                adxs.append(_adx(series))
        return round(_median(adxs), 1) if adxs else None

    def _fetch_top100_breadth(self) -> tuple[float, float, int, list] | None:
        """네이버 시총 페이지에서 KOSPI top100 장중 등락률 → 실측 breadth/momentum.

        fetch_kospi_top100.py와 동일 소스(sise_market_sum). 반환 (breadth, momentum, 표본수, codes).
        표본이 80 미만이면 부분 실패로 보고 None (왜곡된 실측으로 채점 오염 방지).
        """
        import requests
        from bs4 import BeautifulSoup

        naver_hdrs = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.naver.com/',
        }
        codes, rates = [], []
        seen: set = set()
        for page in range(1, 5):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            res = requests.get(url, headers=naver_hdrs, timeout=10)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            table = soup.select_one('table.type_2')
            if not table:
                break
            for row in table.select('tr'):
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                name_tag = cols[1].select_one('a')
                if not name_tag:
                    continue
                code = name_tag['href'].split('code=')[-1]
                if not code.isdigit() or code in seen:
                    continue
                rate_txt = cols[4].get_text(strip=True).replace('%', '').replace(',', '')
                try:
                    rate = float(rate_txt)
                except ValueError:
                    continue
                seen.add(code)
                codes.append(code)
                rates.append(rate)
                if len(codes) >= 100:
                    break
            if len(codes) >= 100:
                break
        if len(codes) < 80:
            return None
        breadth, momentum = self._breadth_momentum(rates)
        return breadth, momentum, len(codes), codes

    def _append_regime_observation(self, now_kst, live_breadth) -> None:
        """국면 관측 이력에 한 건 남긴다 — 10분 해상도, 분 단위 시각.

        라벨러·하네스·판정기가 학습·검증에 쓰는 유일한 원천이다. 나우캐스트의
        `measurements`는 시간당 1건만 남기므로(`_hour_label`) 여기를 대신할 수 없다.

        `live_breadth`가 없으면(수집 실패) 아무것도 쓰지 않는다 — 없는 관측을
        지어내면 이력이 오염된다. 기록 실패가 매매를 막지도 않되 조용히 넘기지도 않는다.
        """
        if not live_breadth:
            return
        try:
            from src.strategy.regime_observations import OBS_PATH_REL, append_observation
            append_observation(
                OBS_PATH_REL,
                now_kst.strftime('%Y-%m-%d %H:%M'),
                live_breadth[0], live_breadth[1],
                self._top100_trend_from_csv(),
                live_breadth[2], 'top100_live')
        except Exception as e:
            self.log_error(f"국면 관측 이력 기록 실패: {e}")

    def _backfill_breadth_kis(self, hhmm: str, codes: list) -> float | None:
        """KIS 당일분봉으로 특정 시각(HH:MM)의 top100 breadth 복원 — 런 결측 백필 전용.

        종목당 1콜(총 ~100콜, 유량제한 초당 20건 고려 0.06s 간격). 표본 80 미만이면 None.
        """
        import time as _time
        if not codes:
            return None
        if self._kis_provider is None:
            from src.trade.kis_data_provider import KISDataProvider
            self._kis_provider = KISDataProvider()
        hhmmss = hhmm.replace(':', '') + '00'
        self.log(f"  [백필] {hhmm} 시점 breadth 복원 시작 ({len(codes)}종목, KIS 분봉)")
        ups, total = 0, 0
        for code in codes:
            d = self._kis_provider.get_minute_price_at(code, hhmmss)
            if d:
                total += 1
                if d['price'] > d['prev_close']:
                    ups += 1
            _time.sleep(0.06)
        if total < 80:
            self.log_error(f"  [백필] 표본 부족({total}) — 채점 보류")
            return None
        breadth = round(ups / total * 100, 1)
        self.log(f"  [백필] {hhmm} breadth={breadth}% (표본 {total})")
        return breadth

    def _get_actual_breadth_from_csv(self, csv_path: str = 'output/kospi_top100_close.csv') -> float | None:
        """KOSPI top100 CSV의 최근 2행으로 오늘 실제 브레드스(상승 종목 비율%) 산출.
        CSV 마지막 행이 오늘 날짜가 아니면(stale) None — 얼어붙은 값을 정답으로 쓰지 않는다."""
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                text = f.read()
        except Exception as e:
            self.log_error(f"KOSPI 브레드스 CSV 산출 실패: {e}")
            return None
        expected_date = self.ctx.now_kst.strftime('%Y%m%d')
        return breadth_from_csv_text(text, expected_date)

    def _fetch_portfolio_prices(self, codes: list) -> dict:
        """
        Buzz Filter 이탈 종목의 현재가를 네이버 금융에서 직접 조회합니다.
        DataFetcherWorker._get_stock_details()와 동일한 URL을 사용합니다.
        frgn.naver 페이지의 첫 번째 데이터 행(data_rows[0][1])이 오늘 종가입니다.
        """
        import re
        import requests
        from bs4 import BeautifulSoup

        prices = {}
        for code in codes:
            try:
                url = f"https://finance.naver.com/item/frgn.naver?code={code}"
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                soup = BeautifulSoup(res.content, 'html.parser')
                rows = soup.select('table.type2 tr')
                data_rows = [
                    r.select('td') for r in rows
                    if len(r.select('td')) == 9
                    and re.match(r'\d{4}', r.select('td')[0].get_text(strip=True))
                ]
                if data_rows:
                    price_text = data_rows[0][1].get_text().replace(',', '').strip()
                    prices[code] = int(price_text) if price_text.isdigit() else 0
                    self.log(f"    {code}: {prices[code]:,}원")
            except Exception as e:
                self.log_error(f"    {code} 현재가 조회 실패: {e}")
        return prices

