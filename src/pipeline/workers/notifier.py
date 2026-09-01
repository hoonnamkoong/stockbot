"""
[V50.1] Stage 4 Worker: 텔레그램 알림 + 최종 저장 (NotifierWorker)
=======================================================
실제 TelegramManager 인터페이스:
  - send_message(text)
  - send_no_data_alert(threshold)
"""

import os
import json
import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData, SyncState
from src.data.storage_manager import StorageManager
from src.telegram_manager import TelegramManager
from src.pipeline.daily_brief import build_daily_brief, collect_sim_brief, should_send_brief
from src.report import gate as report_gate


class NotifierWorker(BaseWorker):
    """
    Stage 4: 텔레그램 발송 + 최종 데이터 저장.
    발송 조건 판단은 daily_brief.should_send_brief()에 위임합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self.tg = TelegramManager()

    def run(
        self,
        all_stocks: list,           # list[dict] (candidates)
        simulation_results: list,   # engine.execute_simulation 결과
        sync_state: SyncState,
    ) -> None:
        """
        텔레그램 발송과 최종 저장을 수행합니다.
        이 메서드의 실패는 파이프라인 전체를 중단시키지 않습니다.
        """
        # 1. 멀티데이 집계 저장
        self._aggregate_multi_day(all_stocks)

        # 2. 브리핑 — 12:00(오전 구간)과 15:00(마감) 둘이 서로 독립이므로,
        # 보낸 슬롯을 그대로 닫아야 한다. 상수를 닫으면 12시를 보내고 15시가
        # 사라진다.
        #
        # 닫는 것은 **발송에 성공했을 때만이다.** 실패를 '보냈다'로 적으면 그날
        # 회차가 통째로 사라진다 — 창(40분)이 아직 열려 있으면 다음 스크래핑
        # 사이클이 재시도할 수 있어야 한다(scrape_gate.mark_scraped와 같은 이유).
        data_dir = getattr(self.ctx, '_report_data_dir', None)
        brief_slot = should_send_brief(self.ctx.now_kst, data_dir)
        if brief_slot:
            if self.safe_run(self._send_daily_brief, self._brief_fallback,
                             brief_slot) is True:
                report_gate.mark_sent(brief_slot, self.ctx.now_kst, data_dir)

        # 3. 실거래 예약 주문 처리
        if self.ctx.is_market_hours():
            self._run_trade_executor()

    def _send_daily_brief(self, slot: str) -> bool:
        """브리핑을 별도 메시지로 발송. 성공했으면 True."""
        from src.trade.balance import get_balance
        from src.pipeline.daily_brief import BRIEF_SPECS

        try:
            balance = get_balance()
        except Exception as e:
            balance = {'error': f'잔고 조회 예외: {e}', 'holdings': []}

        _, since, until = BRIEF_SPECS[slot]
        sims = collect_sim_brief('data', self.ctx.now_kst.strftime('%Y-%m-%d'),
                                 since, until)
        sent = self.tg.send_message(
            build_daily_brief(balance, sims, self.ctx.now_kst, slot))
        if not sent:
            raise RuntimeError(f"{slot} 브리핑 텔레그램 발송 실패")
        self.log(f"{slot} 브리핑 발송 완료")
        return True

    def _brief_fallback(self, slot: str = '') -> None:
        """브리핑 조립·발송 실패. 숫자를 지어내지 않고 실패만 알린다."""
        try:
            self.tg.send_message(
                f"[{self.ctx.now_kst.strftime('%m/%d %H:%M')}] {slot} 브리핑 생성 실패")
        except Exception:
            pass

    def _aggregate_multi_day(self, stocks: list) -> None:
        """5일/3일 누적 보드 데이터를 집계합니다.
        - consecutive_registry에서 연속일수 읽어서 정확하게 반영
        - change_rate가 누락된 종목은 price/prev_close로 재계산
        - 결과 파일은 db-data 브랜치에 보존 (코드 변경 시 초기화 방지)
        """
        # consecutive_registry 로드 (연속일수 정확성 확보)
        try:
            consecutive_counts = self.storage.load_consecutive_registry().get('counts', {})
        except Exception as e:
            self.log_error(f"consecutive_registry 로드 실패: {e}")
            consecutive_counts = {}

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
                code = s.get('code', '')
                old = old_map.get(code, {})

                # 가격 스파크라인 누적
                price = s.get('current_price') or s.get('price', 0)
                spark_p = old.get('sparkline_price', []) + [price]
                spark_n = old.get('sparkline_posts', []) + [s.get('recent_posts_count', 0)]
                s['sparkline_price'] = spark_p[-days:]
                s['sparkline_posts'] = spark_n[-days:]
                s['avg_posts'] = round(sum(s['sparkline_posts']) / len(s['sparkline_posts']), 1) if s['sparkline_posts'] else 0
                s['total_posts'] = sum(s['sparkline_posts'])

                # [Bug 2 Fix] consecutive_registry에서 연속일수 오버라이드
                reg_days = consecutive_counts.get(code, 0)
                s['consecutive_days'] = reg_days if reg_days > 0 else s.get('consecutive_days', 1)

                # [Bug 2 Fix] change_rate 누락 시 재계산
                if not s.get('change_rate'):
                    p = int(s.get('price', s.get('current_price', 0)))
                    pc = int(s.get('prev_close', 0))
                    if p > 0 and pc > 0:
                        rate = ((p - pc) / pc) * 100
                        s['change_rate'] = f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%"
                    else:
                        s['change_rate'] = s.get('change_rate', '0.00%')

                aggregated.append(s)

            try:
                os.makedirs('data', exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(aggregated, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.log_error(f"{days}일 집계 저장 실패: {e}")

        self.log("멀티데이 집계 완료")

    def _run_trade_executor(self) -> None:
        """실거래 예약 주문 처리 엔진을 실행합니다."""
        try:
            from src import trade_executor
            trade_executor.main()
            self.log("TradeExecutor 완료")
        except Exception as e:
            self.log_error(f"TradeExecutor 실행 실패: {e}")
