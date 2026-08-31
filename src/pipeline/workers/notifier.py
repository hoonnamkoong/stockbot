"""
[V50.1] Stage 4 Worker: 텔레그램 알림 + 최종 저장 (NotifierWorker)
=======================================================
실제 TelegramManager 인터페이스:
  - send_dashboard_link()
  - send_market_report(market_name, list)
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
    발송 조건 판단은 PipelineContext.should_notify()에 위임합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self.tg = TelegramManager()

    def run(
        self,
        all_stocks: list,           # list[dict] (candidates)
        simulation_results: list,   # engine.execute_simulation 결과
        final_picks: list,          # 이번 턴 신규 보고 종목 (dict 목록)
        deep_dive_report: str,
        sync_state: SyncState,
    ) -> None:
        """
        텔레그램 발송과 최종 저장을 수행합니다.
        이 메서드의 실패는 파이프라인 전체를 중단시키지 않습니다.
        """
        # 1. 멀티데이 집계 저장
        self._aggregate_multi_day(all_stocks)

        # 슬롯 판정은 **런당 한 번만** 한다. 발송 직후에 슬롯을 닫으므로, 아래에서
        # should_notify()를 다시 물으면 False가 되어 reported_codes 갱신이 조용히
        # 건너뛰어진다. 잡아 쓰고 맨 마지막에 닫는다.
        slot = self.ctx.report_slot() if self.ctx.should_notify() else None
        data_dir = getattr(self.ctx, '_report_data_dir', None)

        # 2. 텔레그램 발송 (슬롯이 열려 있을 때만)
        sent_ok = False
        if slot:
            sent_ok = self.safe_run(
                self._send_report,
                self._send_fallback_summary,
                all_stocks, final_picks, deep_dive_report, sync_state
            ) is True
        else:
            self.log(f"발송 스킵 (이벤트: {self.ctx.github_event}, "
                     f"슬롯 없음: {self.ctx.now_kst.strftime('%H:%M')})")

        # 2-1. 브리핑 — 리포트와 **다른 슬롯이다.** 12:00(오전 구간)과 15:00(마감)
        # 둘이 서로 독립이므로, 보낸 슬롯을 그대로 닫아야 한다. 상수를 닫으면
        # 12시를 보내고 15시가 사라진다.
        brief_slot = should_send_brief(self.ctx.now_kst, data_dir)
        if brief_slot:
            if self.safe_run(self._send_daily_brief, self._brief_fallback,
                             brief_slot) is True:
                report_gate.mark_sent(brief_slot, self.ctx.now_kst, data_dir)

        # 3. reported_codes 상태 업데이트 (현재 수집 종목 추가)
        if slot:
            reported = sync_state.reported_codes
            for s in all_stocks:
                if s.get('code') and s['code'] not in reported:
                    reported.append(s['code'])
            self.storage.save_sync_state(sync_state)

        # 4. 실거래 예약 주문 처리
        if self.ctx.is_market_hours():
            self._run_trade_executor()

        # 5. 슬롯 닫기 — **발송에 성공했을 때만.** 실패를 '보냈다'로 적으면 그날
        # 회차가 통째로 사라진다. 창(40분)이 아직 열려 있으면 다음 스크래핑
        # 사이클이 재시도할 수 있어야 한다(scrape_gate.mark_scraped와 같은 이유).
        if slot and sent_ok:
            report_gate.mark_sent(slot, self.ctx.now_kst, data_dir)
            self.log(f"{slot} 리포트 발송 완료 — 슬롯을 닫습니다")

    def _send_report(
        self,
        all_stocks: list,
        final_picks: list,
        report: str,
        sync_state: SyncState,
    ) -> bool:
        """실제 TelegramManager 메서드로 리포트 발송. 끝까지 갔으면 True.

        반환값으로 슬롯을 닫을지 정한다 — safe_run은 fallback으로 넘어가도 값을
        돌려주므로, 여기서 True를 명시하지 않으면 실패와 성공을 구분할 수 없다.
        """
        # 대시보드 링크 먼저 발송
        self.tg.send_dashboard_link()

        kospi = [s for s in all_stocks if s.get('market') == 'KOSPI']
        kosdaq = [s for s in all_stocks if s.get('market') == 'KOSDAQ']

        if kospi:
            self.tg.send_market_report("KOSPI 실시간 어텐션", kospi)
        if kosdaq:
            self.tg.send_market_report("KOSDAQ 실시간 어텐션", kosdaq)

        if report:
            # 딥다이브 본문(advisor.generate_deep_dive_report)에는 HTML 태그가
            # 하나도 없다. 내용은 Gemini 응답·뉴스 제목·토론 요약을 그대로 담아
            # 'M&A' 같은 문자가 섞이므로, HTML로 보내면 파서가 거부한다.
            self.tg.send_message(report, parse_mode=None)
            self.log(f"딥다이브 리포트 발송 완료 ({len(final_picks)}개 종목)")
        else:
            self.log("시뮬레이션 결과만 발송 완료")

        # 9개 완성 시 순위 정렬 알림 발송
        is_morning = self.ctx.now_kst.hour < 12
        session_complete = sync_state.morning_complete if is_morning else sync_state.afternoon_complete
        
        if session_complete:
            try:
                # 해당 세션의 리스트 가져오기
                reported = sync_state.morning_reported_info if is_morning else sync_state.afternoon_reported_info
                session_name = "오전" if is_morning else "오후"
                
                lines = [f"📋 *오늘의 추천 종목 ({session_name} {len(reported)}개 완성)*\n"]
                # 랭크 순서대로 상위 9개 출력
                for i, item in enumerate(reported[:9], 1):
                    lines.append(f"  {i}위. {item.get('name', '?')}")
                
                lines.append(f"\n📊 분석 리포트: https://stockbot-phi.vercel.app/research")
                self.tg.send_message("\n".join(lines))
                self.log(f"{session_name} 9개 완성 순위 알림 발송")
            except Exception as e:
                self.log_error(f"순위 알림 발송 실패: {e}")

        return True

    def _send_fallback_summary(self, all_stocks, final_picks, report, sync_state) -> None:
        """텔레그램 발송 실패 시 최소한의 정보만 발송."""
        try:
            self.tg.send_message(
                f"[{self.ctx.now_kst.strftime('%m/%d %H:%M')}] 리포트 발송 중 오류\n"
                f"수집 종목: {len(all_stocks)}개 / 보고 대상: {len(final_picks)}개"
            )
        except Exception:
            pass

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
