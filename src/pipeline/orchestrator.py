"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

from src.strategy.regime_state import read_regime
from src.pipeline.context import PipelineContext
from src.data.storage_manager import StorageManager
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.notifier import NotifierWorker


def _status_of(item) -> str:
    """Stage 1은 StockData, Stage 2 이후는 dict를 넘긴다."""
    if isinstance(item, dict):
        return item.get('status', '활성')
    return getattr(item, 'status', '활성')


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

    # ── Stage 1: 데이터 수집 및 1차 필터링 ───────────────────────
    ctx.log("▶ Stage 1: 데이터 수집")
    stocks = DataFetcherWorker(ctx, storage).run()

    # ── Stage 2: AI 분석 ──────────────────────────────────────────
    ctx.log("▶ Stage 2: AI 분석")
    analyzer_worker = LLMAnalyzerWorker(ctx, storage)
    
    if not stocks:
        ctx.log("신규 수집 종목 없음 (Buzz 임계값 미달). 기존 포트폴리오 관리 모드로 진입합니다.")
        # [V50.2] 신규 종목이 없어도 Stage 3(시뮬레이터)를 실행하기 위해 빈 리스트로 계속 진행
        stocks = []
        candidates = []
    else:
        stocks, candidates = analyzer_worker.run(stocks)

    # ── Stage 3: 전략 판단 + 시뮬레이터 동기화 ───────────────────
    ctx.log("▶ Stage 3: 전략 판단 + 시뮬레이터")
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    trade_worker = TradeEngineWorker(ctx, storage)
    final_picks, simulation_results, sell_candidate = trade_worker.run(active_only(stocks), sync_state)

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
        _, _bs = read_regime('data')
        bull_score = 50.0 if _bs is None else _bs

        if strong_picks and bull_score >= 45.0:
            from src.strategy.simulators.sim7_report_follower import ReportFollowerSimulator
            ctx.log(f"▶ Stage 3.6: Sim7 강력 매수 처리 ({len(strong_picks)}개 / bull_score={bull_score:.1f})")
            ReportFollowerSimulator().buy_from_report(strong_picks, bull_score=bull_score)
        else:
            ctx.log(f"▶ Stage 3.6: Sim7 스킵 (강력매수={len(strong_picks)}개 / bull_score={bull_score:.1f})")
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
