"""
[V50] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
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

    각 Worker는 독립 파일/클래스이며, 이 함수는 호출 순서만 정의합니다.
    새 Worker 추가 또는 순서 변경은 이 함수에서만 이루어집니다.
    """
    # 모든 Worker가 공유하는 단일 저장소 인스턴스
    storage = StorageManager()

    ctx.log("=" * 50)
    ctx.log(f"StockBot Pipeline V{PipelineContext.VERSION} 시작")
    ctx.log("=" * 50)

    # Stage 1: 데이터 수집 및 1차 필터링
    ctx.log("▶ Stage 1: 데이터 수집")
    stocks = DataFetcherWorker(ctx, storage).run()

    if not stocks:
        ctx.log("⚠️ 수집된 종목 없음. 파이프라인 종료")
        return

    # Stage 2: AI 분석 (실패 시 Fallback 자동 전환)
    ctx.log("▶ Stage 2: AI 분석")
    stocks = LLMAnalyzerWorker(ctx, storage).run(stocks)

    # Stage 3: 전략 판단 + 시뮬레이터 동기화
    ctx.log("▶ Stage 3: 전략 판단 + 시뮬레이터")
    sync_state, _ = storage.load_sync_state(ctx.today_str)
    trade_worker = TradeEngineWorker(ctx, storage)
    final_picks, simulation_results = trade_worker.run(stocks, sync_state)

    # Stage 4: 딥다이브 리포트 생성 + 텔레그램 발송 + 저장
    ctx.log("▶ Stage 4: 리포트 발송 + 저장")
    if final_picks:
        analyzer_worker = LLMAnalyzerWorker(ctx, storage)
        deep_dive_report = analyzer_worker.generate_deep_dive(final_picks, stocks)
    else:
        deep_dive_report = ""

    sync_state, _ = storage.load_sync_state(ctx.today_str)  # 최신 상태 재로드
    NotifierWorker(ctx, storage).run(stocks, final_picks, deep_dive_report, sync_state)

    ctx.log("=" * 50)
    ctx.log("✅ Pipeline 완료")
    ctx.log("=" * 50)
