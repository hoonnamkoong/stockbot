"""
[V50.1] 파이프라인 오케스트레이터 (Orchestrator)
=======================================================
4개의 Worker를 순서대로 호출합니다.
비즈니스 로직이 없으며, 흐름 제어만 담당합니다.
Worker 인터페이스가 실제 코드와 일치하도록 수정됨.
"""

import json
import os

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
    if not ctx.is_trading_day():
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
        bull_score = 50.0
        try:
            with open(os.path.join('data', 'sim_libero_state.json'), 'r', encoding='utf-8') as _f:
                bull_score = float(json.load(_f).get('bull_score', 50.0))
        except Exception:
            pass

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
