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
from src.data import adopted_registry
from src.strategy import analyzer


def analyze_batch(candidates: list[dict]) -> dict:
    """StrategyAdvisor 호출을 감싸 테스트에서 대체할 수 있게 한다."""
    from src.strategy.advisor import StrategyAdvisor
    return StrategyAdvisor().analyze_batch_discovery(candidates)


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
                # fact_score는 Stage 2에서 계산되지만 이 동기화가 없으면 StockData에
                # 반영되지 않는다 — Stage 3가 s.to_dict()로 다시 만드는 candidates에는
                # 항상 기본값(0.0)만 남아, 계산된 값이 있어도 선정·로깅 어디서도 못 본다.
                try:
                    s.fact_score = float(code_map[s.code].get('fact_score', s.fact_score))
                except (TypeError, ValueError):
                    pass

        return stocks, candidates

    def _run_with_ai(self, candidates: list[dict]) -> list[dict]:
        """Gemini 배치 분석 (활성 종목만). 추적 종목은 캐시된 요약을 재사용한다."""
        self._analyze_active(candidates)
        self._apply_cached_ai(candidates)
        self._persist(candidates)
        self.log("AI 분석 완료")
        return candidates

    def _analyze_active(self, candidates: list[dict]) -> None:
        """활성 종목만 Gemini 배치 분석 대상으로 삼는다 (비용 절감)."""
        active = [c for c in candidates if c.get('status', '활성') == '활성']
        if not active:
            return
        self.log(f"AI 배치 분석 시작 ({len(active)}개 종목)")
        time.sleep(2)  # 429 방어용 지연
        batch_results = analyze_batch(active)

        for s in active:
            code = s['code']
            if code in batch_results:
                ai = batch_results[code]
                s['posts_summary'] = ai.get('summary', '분석 오류')
                s['sentiment'] = str(ai.get('sentiment', 'Neutral'))
                s['keywords'] = ai.get('keywords', [])
                # [Sim1] 팩트 근거 강도. 진입 필터가 아니라 보유기간·목표가 분기용이다.
                try:
                    s['fact_score'] = float(ai.get('fact_score', 0.0))
                except (TypeError, ValueError):
                    s['fact_score'] = 0.0

            # Fallback: AI 결과가 비어있는 경우
            if s.get('posts_summary') in [None, "분석 대기중", "분석 오류", "AI 분석 불가", ""]:
                kws = ", ".join(s.get('keywords', [])) or "시장 주도주"
                s['posts_summary'] = f"[데이터 분석] '{kws}' 중심 {s.get('recent_posts_count', 0)}건 토론 포착"

    def _apply_cached_ai(self, candidates: list[dict]) -> None:
        """추적 종목에는 마지막으로 활성이었을 때의 AI 결과를 붙인다."""
        registry = adopted_registry.load(self.ctx.today_str)
        for s in candidates:
            if s.get('status') != '추적':
                continue
            ai = registry.get(s['code'], {}).get('ai', {})
            s['posts_summary'] = ai.get('posts_summary', '추적 중 (신규 게시글 적음)')
            s['sentiment'] = ai.get('sentiment', 'Neutral')
            s['keywords'] = ai.get('keywords', [])

    def _persist(self, candidates: list[dict]) -> bool:
        """엑셀·대시보드에 기록한다. 반쪽 런은 기록하지 않는다.

        월간 엑셀은 누적 append라 한 번 들어간 반쪽 데이터를 되돌릴 수 없고,
        대시보드는 전량 덮어쓰기라 멀쩡한 스냅샷이 사라진다.
        """
        if self.ctx.scrape_degraded():
            self.log_error(
                f"수집 실패율 초과 → 이번 런은 기록하지 않습니다 "
                f"(페이지 {self.ctx.scrape_pages_failed}/{self.ctx.scrape_pages_total} 실패)"
            )
            return False

        df_final, _ = analyzer.analyze_discussion_trend(candidates)
        analyzer.save_data(df_final)
        self.storage.save_latest_stocks(candidates, self.ctx.now_kst)
        self._update_registry(candidates)
        return True

    def _update_registry(self, candidates: list[dict]) -> None:
        """활성 종목의 AI 결과를 채택 레지스트리에 반영한다 (건강한 런에서만 호출됨)."""
        registry = adopted_registry.load(self.ctx.today_str)
        for s in candidates:
            if s.get('status', '활성') != '활성':
                continue
            entry = registry.setdefault(s['code'], {})
            entry['name'] = s.get('name', entry.get('name', ''))
            entry['market'] = s.get('market', entry.get('market', ''))
            # Gemini가 일부 종목을 배치 결과에서 누락하면 s에 'keywords' 키 자체가
            # 없을 수 있다. s.get(key, 기본값)으로 바로 쓰면 기존에 캐시된 값을
            # 빈 기본값으로 덮어써버리므로, 기존 항목을 기본값으로 사용한다.
            prev_ai = entry.get('ai', {})
            entry['ai'] = {
                'posts_summary': s.get('posts_summary', prev_ai.get('posts_summary', '')),
                'sentiment': s.get('sentiment', prev_ai.get('sentiment', 'Neutral')),
                'keywords': s.get('keywords', prev_ai.get('keywords', [])),
            }
        adopted_registry.save(self.ctx.today_str, registry)

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

        self._apply_cached_ai(candidates)

        # Fallback에서도 데이터 저장
        try:
            self._persist(candidates)
        except Exception as e:
            self.log_error(f"Fallback 저장 실패: {e}")

        self.log("규칙 기반 Fallback 완료")
        return candidates

    def generate_deep_dive(self, final_picks: list[dict], all_candidates: list[dict], sell_candidate: dict = None) -> str:
        """딥다이브 리포트 생성. 실패 시 빈 문자열 반환."""
        if not final_picks and not sell_candidate:
            return ""
        try:
            time.sleep(2)
            from src.strategy.advisor import StrategyAdvisor
            advisor = StrategyAdvisor()
            
            # 1. 추천 종목 풀 데이터 구성
            detail_picks = []
            for p in final_picks:
                full = next((c for c in all_candidates if c['code'] == p['code']), p).copy()
                full['rank'] = p.get('rank')
                detail_picks.append(full)
                
            # 2. 리포트 생성 (추천 2개 + 매도 1개)
            report_str = advisor.generate_deep_dive_report(detail_picks, sell_candidate=sell_candidate)
            
            # 3. 상세 텍스트 및 추천 등급 백필
            for p in final_picks:
                dp = next((c for c in detail_picks if c['code'] == p['code']), None)
                if dp:
                    if 'deep_dive_text' in dp:
                        p['deep_dive_text'] = dp['deep_dive_text']
                    if 'rank_and_recommendation' in dp:
                        p['rank_and_recommendation'] = dp['rank_and_recommendation']
            return report_str
        except Exception as e:
            self.log_error(f"딥다이브 리포트 생성 실패: {e}")
            return ""
