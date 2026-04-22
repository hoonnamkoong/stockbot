"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

from src.pipeline.context import PipelineContext
from src.data.storage_manager import StorageManager
from src.pipeline.workers.data_fetcher import DataFetcherWorker
from src.pipeline.workers.llm_analyzer import LLMAnalyzerWorker
from src.pipeline.workers.trade_engine import TradeEngineWorker
from src.pipeline.workers.notifier import NotifierWorker


def run_pipeline(ctx: PipelineContext) -> None:
    """
    StockBot 메인 파이프라인을 실행합니다.
    Stage 1 → 2 → 3 → 4 순서로 Worker를 호출합니다.
    """
    storage = StorageManager()

    ctx.log("=" * 50)
    ctx.log(f"StockBot Pipeline V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # ── Stage 1: 데이터 수집 및 1차 필터링 ───────────────────────
    ctx.log("▶ Stage 1: 데이터 수집")
    stocks = DataFetcherWorker(ctx, storage).run()

    if not stocks:
        ctx.log("수집된 종목 없음. 파이프라인 종료")
        return

    # ── Stage 2: AI 분석 ──────────────────────────────────────────
    ctx.log("▶ Stage 2: AI 분석")
    analyzer_worker = LLMAnalyzerWorker(ctx, storage)
    stocks, candidates = analyzer_worker.run(stocks)

    # ── Stage 3: 전략 판단 + 시뮬레이터 동기화 ───────────────────
    ctx.log("▶ Stage 3: 전략 판단 + 시뮬레이터")
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    trade_worker = TradeEngineWorker(ctx, storage)
    final_picks, simulation_results = trade_worker.run(stocks, sync_state)

    # ── Stage 3.5: 딥다이브 리포트 생성 ──────────────────────────
    deep_dive_report = ""
    if ctx.should_notify():
        if final_picks:
            ctx.log(f"▶ Stage 3.5: 딥다이브 리포트 생성 ({len(final_picks)}개 종목)")
            deep_dive_report = analyzer_worker.generate_deep_dive(final_picks, candidates)
            # 월별 리서치 엑셀에도 기록
            storage.update_monthly_excel(final_picks, ctx.now_kst)
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

    # ── Stage 4: 텔레그램 발송 + 최종 저장 ───────────────────────
    ctx.log("▶ Stage 4: 리포트 발송 + 저장")
    # 최신 sync_state 재로드 (Stage 3에서 업데이트됐을 수 있음)
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    NotifierWorker(ctx, storage).run(
        all_stocks=candidates,
        simulation_results=simulation_results,
        final_picks=final_picks,
        deep_dive_report=deep_dive_report,
        sync_state=sync_state,
    )

    ctx.log("=" * 50)
    ctx.log("Pipeline 완료")
    ctx.log("=" * 50)
