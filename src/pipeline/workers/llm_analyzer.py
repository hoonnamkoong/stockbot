"""
[V50] Stage 2 Worker: AI 분석기 (LLMAnalyzerWorker)
=======================================================
Gemini AI를 사용해 수집된 종목의 토론 내용을 분석합니다.
AI API 장애 시 자동으로 규칙 기반 Fallback으로 전환합니다.

기존 scraper.py의 Stage 2 로직을 이 클래스로 이전했습니다.
"""

import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData
from src.data.storage_manager import StorageManager
from src.strategy.advisor import StrategyAdvisor
from src.strategy import analyzer


class LLMAnalyzerWorker(BaseWorker):
    """
    Stage 2: Gemini AI 배치 분석 + 딥다이브 리포트 생성.
    API 한도 초과(429) 또는 타임아웃 시 규칙 기반 Fallback으로 계속 실행됩니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self.advisor = StrategyAdvisor()

    def run(self, stocks: list[StockData]) -> list[StockData]:
        """
        AI 배치 분석을 실행합니다. 실패 시 Fallback.
        Returns:
            posts_summary, sentiment 등이 채워진 StockData 목록
        """
        if not stocks:
            return stocks

        # safe_run으로 AI 분석 → Fallback 자동 전환
        enriched = self.safe_run(
            self._run_with_ai,
            self._run_rule_based_fallback,
            stocks
        )
        return enriched if enriched is not None else stocks

    def _run_with_ai(self, stocks: list[StockData]) -> list[StockData]:
        """Gemini AI를 사용한 배치 분석 (Primary)"""
        self.log(f"AI 배치 분석 시작 ({len(stocks)}개 종목)")
        time.sleep(2)  # 429 방어용 지연

        # dict 형태로 변환하여 기존 advisor 호환
        stocks_dict = [s.to_dict() for s in stocks]
        batch_results = self.advisor.analyze_batch_discovery(stocks_dict)

        for s in stocks:
            if s.code in batch_results:
                ai = batch_results[s.code]
                s.posts_summary = ai.get('summary', '분석 오류')
                s.sentiment = str(ai.get('sentiment', 'Neutral'))
                s.top_keywords = ai.get('keywords', [])

            # Fallback: AI 결과가 비어있거나 placeholder인 경우
            if s.posts_summary in [None, "분석 대기중", "분석 오류", "AI 분석 불가", ""]:
                kws = ", ".join(s.top_keywords) if s.top_keywords else "시장 주도주"
                s.posts_summary = f"[데이터 분석] '{kws}' 중심 {s.recent_posts_count}건 토론 포착"

        # 대시보드 데이터 저장 (analyzer 호환 유지)
        df_final, _ = analyzer.analyze_discussion_trend(stocks_dict)
        analyzer.save_data(df_final)
        self.storage.save_latest_stocks(stocks, self.ctx.now_kst)

        self.log("AI 분석 완료")
        return stocks

    def _run_rule_based_fallback(self, stocks: list[StockData]) -> list[StockData]:
        """
        AI를 사용할 수 없을 때의 규칙 기반 대체 분석 (Fallback).
        게시글 수, 외인비중 데이터만으로 요약을 생성합니다.
        """
        self.log("🔄 규칙 기반 Fallback 모드 실행 중")
        for s in stocks:
            direction = "매집" if s.foreign_change > 0 else "이탈"
            s.posts_summary = (
                f"[Fallback] {s.recent_posts_count}건 포착 / "
                f"외인 {direction} {abs(s.foreign_change):.2f}%p"
            )
            s.sentiment = "Positive" if s.foreign_change > 0 else "Negative"

        # Fallback에서도 데이터 저장은 수행
        try:
            self.storage.save_latest_stocks(stocks, self.ctx.now_kst)
        except Exception as e:
            self.log_error(f"Fallback 저장 실패: {e}")

        self.log("규칙 기반 Fallback 완료")
        return stocks

    def generate_deep_dive(
        self,
        picks: list[StockData],
        all_stocks: list[StockData]
    ) -> str:
        """
        최종 선별된 종목에 대한 딥다이브 리포트를 생성합니다.
        실패 시 빈 문자열 반환 (파이프라인 중단 없음).
        """
        if not picks:
            return ""
        try:
            detail_picks = []
            for p in picks:
                full = next((s for s in all_stocks if s.code == p.code), p)
                detail_picks.append(full.to_dict())
            return self.advisor.generate_deep_dive_report(detail_picks)
        except Exception as e:
            self.log_error(f"딥다이브 리포트 생성 실패: {e}")
            return ""
