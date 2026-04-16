"""
[V50] Stage 4 Worker: 텔레그램 알림 + 최종 저장 (NotifierWorker)
=======================================================
분석 결과를 텔레그램으로 발송하고 모든 최종 데이터를 저장합니다.
발송 실패가 매매 로직에 영향을 주지 않습니다 (완전 격리).

기존 scraper.py의 Stage 4 텔레그램/저장 로직을 이 클래스로 이전했습니다.
"""

import os
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData, SyncState
from src.data.storage_manager import StorageManager
from src.telegram_manager import TelegramManager


class NotifierWorker(BaseWorker):
    """
    Stage 4: 텔레그램 발송 + 최종 데이터 저장.
    발송 조건 판단은 PipelineContext.should_notify()에 위임합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self.tg = TelegramManager()

    def run(
        self,
        all_stocks: list[StockData],
        final_picks: list[StockData],
        deep_dive_report: str,
        sync_state: SyncState,
    ) -> None:
        """
        텔레그램 발송과 최종 저장을 수행합니다.
        이 메서드의 실패는 파이프라인 전체를 중단시키지 않습니다.
        """
        # 1. 5일/3일 누적 집계 저장
        self._aggregate_multi_day(all_stocks)

        # 2. 텔레그램 발송 (조건 충족 시에만)
        if self.ctx.should_notify():
            self.safe_run(
                self._send_report,
                self._send_fallback_summary,
                all_stocks, final_picks, deep_dive_report
            )
        else:
            self.log(f"발송 스킵 (이벤트: {self.ctx.github_event}, 분: {self.ctx.start_minute})")

    def _send_report(
        self,
        all_stocks: list[StockData],
        final_picks: list[StockData],
        report: str,
    ) -> None:
        """딥다이브 리포트 또는 시장 요약을 텔레그램으로 발송합니다."""
        if report and "[안내]" not in report:
            all_stocks_dict = [s.to_dict() for s in all_stocks]
            self.tg.send_chart_report(all_stocks_dict, report)
            self.log(f"딥다이브 리포트 발송 완료 ({len(final_picks)}개 종목)")
        else:
            # 신규 종목이 없을 때 시장 현황 요약 발송
            dashboard_url = os.environ.get("DASHBOARD_URL", "https://stockbot-phi.vercel.app")
            daily_info = [item['name'] for item in (
                [] # sync_state는 TradeEngineWorker에서 이미 처리됨
            )]

            msg = (
                f"📊 [{self.ctx.now_kst.strftime('%m/%d %H:%M')}] 시장 모니터링\n\n"
                f"현재 {len(all_stocks)}개 종목 포착 (임계: {self.ctx.threshold}건)\n"
                f"새 특이 종목 감지 즉시 딥다이브 발행 예정\n\n"
                f"📈 {dashboard_url}/research"
            )
            self.tg.send_message(msg)
            self.log("시장 요약 발송 완료")

    def _send_fallback_summary(self, all_stocks, final_picks, report) -> None:
        """텔레그램 발송 실패 시 최소한의 정보만 발송합니다."""
        try:
            self.tg.send_message(
                f"⚠️ [{self.ctx.now_kst.strftime('%m/%d %H:%M')}] 리포트 발송 중 오류 발생\n"
                f"수집 종목: {len(all_stocks)}개 / 보고 대상: {len(final_picks)}개"
            )
        except Exception:
            pass

    def _aggregate_multi_day(self, stocks: list[StockData]) -> None:
        """5일/3일 누적 보드 데이터를 집계합니다."""
        import json
        import os

        for days in [3, 5]:
            filepath = f"data/analysis_{days}days.json"
            old_map = {}

            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        old_map = {item['code']: item for item in json.load(f)}
                except Exception:
                    pass

            aggregated = []
            for s in stocks:
                old = old_map.get(s.code, {})
                spark_p = old.get('sparkline_price', []) + [s.price]
                spark_n = old.get('sparkline_posts', []) + [s.recent_posts_count]
                s_dict = s.to_dict()
                s_dict['sparkline_price'] = spark_p[-days:]
                s_dict['sparkline_posts'] = spark_n[-days:]
                s_dict['avg_posts'] = sum(s_dict['sparkline_posts']) / len(s_dict['sparkline_posts']) if s_dict['sparkline_posts'] else 0
                s_dict['total_posts'] = sum(s_dict['sparkline_posts'])
                aggregated.append(s_dict)

            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(aggregated, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.log_error(f"{days}일 집계 저장 실패: {e}")

        self.log("멀티데이 집계 완료")
