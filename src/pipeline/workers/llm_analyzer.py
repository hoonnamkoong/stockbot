"""
[V50.1] Stage 2 Worker: AI 분석기 (LLMAnalyzerWorker)
=======================================================
실제 advisor 인터페이스:
  - StrategyAdvisor.analyze_batch_discovery(list[dict]) → dict
  - StrategyAdvisor.generate_deep_dive_report(list[dict]) → str
  - analyzer.analyze_discussion_trend(list[dict]) → (DataFrame, _)
  - analyzer.save_data(df, ...) → None
"""

import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData
from src.data.storage_manager import StorageManager
from src.strategy import analyzer


class LLMAnalyzerWorker(BaseWorker):
    """
    Stage 2: Gemini AI 배치 분석 + 딥다이브 리포트 생성.
    API 한도 초과(429) 또는 타임아웃 시 규칙 기반 Fallback 자동 전환.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage

    def run(self, stocks: list[StockData]) -> tuple[list[StockData], list[dict]]:
        """
        AI 배치 분석을 실행합니다.

        Returns:
            (enriched_stocks, candidates_dict)
            - enriched_stocks: posts_summary가 채워진 StockData 목록
            - candidates_dict: dict 목록 (이후 Stage에서 사용)
        """
        if not stocks:
            return stocks, []

        # dict 변환 (advisor 호환)
        candidates = [s.to_dict() for s in stocks]

        # AI 분석 (실패 시 Fallback 자동 전환)
        candidates = self.safe_run(
            self._run_with_ai,
            self._run_rule_based_fallback,
            candidates
        )
        if candidates is None:
            candidates = [s.to_dict() for s in stocks]

        # 분석 결과를 StockData로 다시 동기화
        code_map = {c['code']: c for c in candidates}
        for s in stocks:
            if s.code in code_map:
                s.posts_summary = code_map[s.code].get('posts_summary', s.posts_summary)
                s.sentiment = str(code_map[s.code].get('sentiment', s.sentiment))
                s.top_keywords = code_map[s.code].get('keywords', s.top_keywords)

        return stocks, candidates

    def _run_with_ai(self, candidates: list[dict]) -> list[dict]:
        """Gemini AI를 사용한 배치 분석 (Primary)."""
        self.log(f"AI 배치 분석 시작 ({len(candidates)}개 종목)")
        time.sleep(2)  # 429 방어용 지연

        from src.strategy.advisor import StrategyAdvisor
        advisor = StrategyAdvisor()
        batch_results = advisor.analyze_batch_discovery(candidates)

        for s in candidates:
            code = s['code']
            if code in batch_results:
                ai = batch_results[code]
                s['posts_summary'] = ai.get('summary', '분석 오류')
                s['sentiment'] = str(ai.get('sentiment', 'Neutral'))
                s['keywords'] = ai.get('keywords', [])

            # Fallback: AI 결과가 비어있는 경우
            if s.get('posts_summary') in [None, "분석 대기중", "분석 오류", "AI 분석 불가", ""]:
                kws = ", ".join(s.get('keywords', [])) or "시장 주도주"
                s['posts_summary'] = f"[데이터 분석] '{kws}' 중심 {s.get('recent_posts_count', 0)}건 토론 포착"

        # 대시보드용 데이터 저장 (기존 방식 유지)
        df_final, _ = analyzer.analyze_discussion_trend(candidates)
        analyzer.save_data(df_final)
        self.storage.save_latest_stocks(candidates, self.ctx.now_kst)

        self.log("AI 분석 완료")
        return candidates

    def _run_rule_based_fallback(self, candidates: list[dict]) -> list[dict]:
        """AI 장애 시 규칙 기반 Fallback."""
        self.log("규칙 기반 Fallback 모드 실행")
        for s in candidates:
            direction = "매집" if s.get('foreign_change', 0) > 0 else "이탈"
            s['posts_summary'] = (
                f"[Fallback] {s.get('recent_posts_count', 0)}건 포착 / "
                f"외인 {direction} {abs(s.get('foreign_change', 0)):.2f}%p"
            )
            s['sentiment'] = "Positive" if s.get('foreign_change', 0) > 0 else "Negative"

        # Fallback에서도 데이터 저장
        try:
            df_final, _ = analyzer.analyze_discussion_trend(candidates)
            analyzer.save_data(df_final)
            self.storage.save_latest_stocks(candidates, self.ctx.now_kst)
        except Exception as e:
            self.log_error(f"Fallback 저장 실패: {e}")

        self.log("규칙 기반 Fallback 완료")
        return candidates

    def generate_deep_dive(self, final_picks: list[dict], all_candidates: list[dict]) -> str:
        """딥다이브 리포트 생성. 실패 시 빈 문자열 반환."""
        if not final_picks:
            return ""
        try:
            time.sleep(2)
            from src.strategy.advisor import StrategyAdvisor
            advisor = StrategyAdvisor()
            # final_picks의 코드로 풀 데이터 조회
            detail_picks = []
            for p in final_picks:
                full = next((c for c in all_candidates if c['code'] == p['code']), p)
                detail_picks.append(full)
            return advisor.generate_deep_dive_report(detail_picks)
        except Exception as e:
            self.log_error(f"딥다이브 리포트 생성 실패: {e}")
            return ""
