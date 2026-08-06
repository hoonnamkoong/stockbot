"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

from src.strategy.regime_state import read_regime
from src.strategy.registry import needs_buzz as sim_needs_buzz
from src.pipeline.context import PipelineContext
from src.data.storage_manager import StorageManager
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.program_trader import run_program_trading, peek_selected_sim
from src.pipeline.workers.notifier import NotifierWorker


def _status_of(item) -> str:
    """Stage 1은 StockData, Stage 2 이후는 dict를 넘긴다."""
    if isinstance(item, dict):
        return item.get('status', '활성')
    return getattr(item, 'status', '활성')


SIM7_BULL_SCORE_MIN = 45.0


def sim7_should_buy(strong_picks: list, bull_score) -> bool:
    """Stage 3.6 게이트 — '강력 매수'가 있고 장이 죽지 않았을 때만 산다.

    bull_score가 None이면 사지 않는다. 예전에는 국면 파일 조회에 실패하면
    50.0으로 폴백했고, 그 지어낸 점수가 45 게이트를 그대로 통과해 실제 매수가
    나갔다. 모르는 것은 '보통 장'이 아니다.
    """
    return bool(strong_picks) and bull_score is not None and bull_score >= SIM7_BULL_SCORE_MIN


def active_only(items: list) -> list:
    """추적 종목은 기록(엑셀·대시보드)용이다.

    매매·시뮬레이터·텔레그램 리포트·누적 보드에는 활성 종목만 넘긴다.
    """
    return [x for x in items if _status_of(x) == '활성']


def _notify_holiday_check_failed(ctx: PipelineContext) -> None:
    """거래일 판정 불가를 알린다.

    should_notify()의 정각(0~2분) 제한을 일부러 우회한다 — 이건 리포트가
    아니라 "봇이 멈췄다"는 장애 신호이고, 15/30/45분 런에서 침묵하면
    장애를 놓친다.
    """
    try:
        from src.telegram_manager import TelegramManager
        sent = TelegramManager().send_message(
            f"⚠️ <b>휴장 판정 실패</b>\n\n"
            f"{ctx.today_display} — 거래일 여부를 확인하지 못해 봇을 정지했습니다.\n"
            f"KIS chk-holiday 조회에 실패했습니다.\n\n"
            f"수동 실행: scraper.yml → Run workflow → force_run 체크\n"
            f"⚠️ <b>먼저 오늘이 휴장일이 아님을 직접 확인한 뒤에만 사용하세요.</b>\n"
            f"이 옵션은 휴장일 게이트를 완전히 우회하며, 켜면 실매수 주문이 나갑니다."
        )
        if not sent:
            ctx.log("[경고] 판정 실패 알림 발송에 실패했습니다: send_message가 False를 반환했습니다.")
    except Exception as e:
        ctx.log(f"[경고] 판정 실패 알림 발송에 실패했습니다: {e}")


def trade_if_buzz_free(ctx: PipelineContext, trade_worker, regime: str | None) -> str | None:
    """실전 선택 심이 버즈를 안 쓰면 스크래핑을 기다리지 않고 매매를 낸다(E3).

    스크래퍼(10분)의 Stage 0.5와 trade_lite(2분)가 같은 코드를 쓴다 — 갈리면
    두 경로의 동작이 어긋나고, 그건 program-trading-parity를 깨는 방식이다.

    반환: 이번 호출에서 실제로 매매한 심 id, 안 했으면 None.

    bool이 아니라 sim_id를 돌려주는 이유: 호출부가 "방금 무엇을 매매했는지" 알아야
    할 때(예: trade_lite의 페이퍼 동기화) config를 다시 조회하면 안 된다 — 매매
    실행 중(수초~수십초) config가 바뀌면 다른 심을 조회하게 되는 레이스가 생긴다.
    이 함수가 실제로 매매를 결정한 그 값을 그대로 넘겨준다.
    """
    selected_sim = None
    try:
        selected_sim = peek_selected_sim(log=ctx.log)
    except Exception as e:
        ctx.log(f"[경고] 선택 심 조회 실패 — 스크래핑 후 매매(느린 경로)로 진행: {e}")
        return None

    if not selected_sim:
        ctx.log("[Program] 선택된 심 없음(OFF) — 순서 변경 없음")
        return None

    try:
        buzz_free = not sim_needs_buzz(selected_sim, regime)
    except Exception as e:
        # registry.needs_buzz()는 매니페스트에 없는 심이나 dynamic 심에
        # classmethod가 없으면 예외를 던진다. 모르는 것을 "버즈 불필요"로 읽으면
        # 스크래핑 없이 잘못된 유니버스로 매매가 나갈 수 있다 — 느린 경로로 미룬다.
        ctx.log(f"[경고] needs_buzz 판정 실패 — 스크래핑 후 매매(느린 경로)로 진행: {e}")
        return None

    if buzz_free:
        ctx.log(f"[Program] '{selected_sim}' 버즈 불필요(국면={regime}) — 스크래핑 전에 매매 실행")
        try:
            run_program_trading(
                [], is_market_hours=ctx.is_market_hours(), now_kst=ctx.now_kst,
                log=trade_worker.log, log_error=trade_worker.log_error,
                enrich=trade_worker._enrich_universe,
            )
            return selected_sim
        except Exception as e:
            ctx.log(f"[경고] 조기 프로그램 매매 실패 — Stage 3에서 재시도: {e}")
            return None

    ctx.log(f"[Program] '{selected_sim}' 버즈 필요(국면={regime}) — 스크래핑 후 매매")
    return None


def run_pipeline(ctx: PipelineContext) -> None:
    """
    StockBot 메인 파이프라인을 실행합니다.
    Stage 1 → 2 → 3 → 4 순서로 Worker를 호출합니다.
    """
    storage = StorageManager()

    ctx.log("=" * 50)
    ctx.log(f"StockBot Pipeline V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # ── 휴장일 체크 ──────────────────────────────────────────
    # is_trading_day()는 3값이다. None(판정 불가)을 휴장과 뭉뚱그리면
    # 조용히 멈추고, True로 폴백하면 휴장일에 돈다. 둘 다 갈라서 처리한다.
    trading = ctx.is_trading_day()
    if trading is None:
        ctx.log(f"[중단] 거래일 여부를 판정할 수 없습니다({ctx.today_display}).")
        _notify_holiday_check_failed(ctx)
        return
    if not trading:
        ctx.log(f"오늘은 휴장일({ctx.today_display})입니다. 파이프라인을 종료합니다.")
        return

    # ── Stage 0: 국면 판단 + 순서 가변 분기(E3) ───────────────────
    # 실전 계좌가 선택한 심이 네이버 게시글(버즈)을 안 쓰면(needs_buzz=False),
    # 스크래핑(Stage 1)을 기다리지 않고 매매부터 낸다. Sim0(리베로) 국면 갱신은
    # top100 라이브 실측만으로 가능해졌다(E2) — 이게 이 분기의 유일한 입력이라
    # 스크래핑보다 먼저 돈다. Sim10처럼 국면에 따라 필요 여부가 바뀌는 심도
    # registry.needs_buzz()가 국면을 받아 판단한다.
    trade_worker = TradeEngineWorker(ctx, storage)
    with ctx.stage("Stage 0: 국면 판단"):
        regime = trade_worker.run_regime_stage()

    with ctx.stage("Stage 0.5: 매매 순서 분기"):
        # trade_if_buzz_free는 이제 sim_id|None을 돌려준다(trade_lite가 재조회 없이
        # 쓰려고). 여기서는 bool만 필요하므로 명시적으로 좁힌다.
        program_traded_early = trade_if_buzz_free(ctx, trade_worker, regime) is not None

    # ── Stage 1: 데이터 수집 및 1차 필터링 ───────────────────────
    with ctx.stage("Stage 1: 데이터 수집"):
        stocks = DataFetcherWorker(ctx, storage).run()

    # ── Stage 2: AI 분석 ──────────────────────────────────────────
    analyzer_worker = LLMAnalyzerWorker(ctx, storage)
    with ctx.stage("Stage 2: AI 분석"):
        if not stocks:
            ctx.log("신규 수집 종목 없음 (Buzz 임계값 미달). 기존 포트폴리오 관리 모드로 진입합니다.")
            # [V50.2] 신규 종목이 없어도 Stage 3(시뮬레이터)를 실행하기 위해 빈 리스트로 계속 진행
            stocks = []
            candidates = []
        else:
            stocks, candidates = analyzer_worker.run(stocks)

    # ── Stage 3: 전략 판단 + 시뮬레이터 동기화 ───────────────────
    # trade_worker는 Stage 0에서 만든 것을 그대로 쓴다(새로 만들면 _kis_provider
    # 캐시가 갈리고, sim0_libero를 다시 도는 실수를 하기도 쉽다).
    with ctx.stage("Stage 3: 전략 판단 + 시뮬레이터"):
        sync_state, _ = storage.load_sync_state(ctx.today_str)
        final_picks, simulation_results, sell_candidate = trade_worker.run(
            active_only(stocks), sync_state, skip_program_trading=program_traded_early)

    # ── Stage 3.5: 딥다이브 리포트 생성 ──────────────────────────
    deep_dive_report = ""
    if ctx.should_notify():
        # [User V50.8] 상세 리포트 대상: 추천 상위 2개 + 매도 후보 1개
        if final_picks or sell_candidate:
            ctx.log(f"▶ Stage 3.5: 딥다이브 리포트 생성 (추천:{len(final_picks[:2])}개, 매도:{1 if sell_candidate else 0}개)")
            deep_dive_report = analyzer_worker.generate_deep_dive(final_picks[:2], candidates, sell_candidate=sell_candidate)
            # 월별 리서치 엑셀에도 기록
            if final_picks:
                storage.update_monthly_excel(final_picks[:2], ctx.now_kst)
        else:
            # 오늘 이미 보고된 종목들만 있는 경우
            daily_info = sync_state.daily_reported_info
            if simulation_results and any(r.get('signal') in ['BUY', 'WATCH'] for r in simulation_results):
                names_str = ", ".join(item['name'] for item in daily_info)
                dashboard_url = "https://stockbot-phi.vercel.app/api/download/excel"
                deep_dive_report = (
                    f"[안내] 이번 회차의 모든 종목은 오늘 이미 보고되었습니다.\n"
                    f"오늘 보고 종목: {names_str}\n\n"
                    f"리포트 다운로드: {dashboard_url}"
                )
    else:
        ctx.log("▶ Stage 3.5: 정각 발송 타이밍 아님 (딥다이브 생성 생략)")

    if not final_picks:
        # [Bug 1 Fix] 신규 picks 없어도 reports.json 항상 재생성
        storage.rebuild_reports_index(ctx.now_kst)

    # ── Stage 3.6: Sim7 신규 매수 ────────────────────────────────
    # rank_and_recommendation이 final_picks에 역전파된 이후 실행
    try:
        strong_picks = [
            p for p in final_picks
            if '강력 매수' in (p.get('rank_and_recommendation') or '')
        ]
        _, bull_score = read_regime('data')

        if sim7_should_buy(strong_picks, bull_score):
            from src.strategy.simulators.sim7_report_follower import ReportFollowerSimulator
            ctx.log(f"▶ Stage 3.6: Sim7 강력 매수 처리 ({len(strong_picks)}개 / bull_score={bull_score:.1f})")
            ReportFollowerSimulator().buy_from_report(strong_picks, bull_score=bull_score)
        else:
            score_txt = '측정 불가' if bull_score is None else f'{bull_score:.1f}'
            ctx.log(f"▶ Stage 3.6: Sim7 스킵 (강력매수={len(strong_picks)}개 / bull_score={score_txt})")
    except Exception as _e:
        ctx.log(f"[Warn] Stage 3.6 Sim7 실패: {_e}")

    # ── Stage 4: 텔레그램 발송 + 최종 저장 ───────────────────────
    ctx.log("▶ Stage 4: 리포트 발송 + 저장")
    # 최신 sync_state 재로드 (Stage 3에서 업데이트됐을 수 있음)
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    # 추적 종목은 5일/3일 누적 보드(_aggregate_multi_day), 텔레그램 종목 수,
    # reported_codes에 섞이면 안 된다. 이 인자가 그 넷의 유일한 입구다.
    NotifierWorker(ctx, storage).run(
        all_stocks=active_only(candidates),
        simulation_results=simulation_results,
        final_picks=final_picks,
        deep_dive_report=deep_dive_report,
        sync_state=sync_state,
    )

    ctx.log("=" * 50)
    ctx.log("Pipeline 완료")
    ctx.log("=" * 50)
