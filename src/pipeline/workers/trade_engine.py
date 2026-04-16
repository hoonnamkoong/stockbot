"""
[V50] Stage 3 Worker: 전략 판단 + 시뮬레이터 (TradeEngineWorker)
=======================================================
YAML Manifest에서 로드된 전략과 시뮬레이터를 실행합니다.
새 전략/시뮬레이터 추가 시 이 파일은 수정하지 않습니다.

기존 scraper.py의 Stage 3/5 로직을 이 클래스로 이전했습니다.
"""

import os
import json
import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData, SyncState
from src.data.storage_manager import StorageManager
from src.strategy.registry import get_current_strategy, get_active_simulators


class TradeEngineWorker(BaseWorker):
    """
    Stage 3: 전략 판단(BUY/WATCH) + 시뮬레이터 주가 동기화.
    Registry에서 전략과 시뮬레이터를 자동으로 로드합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage

    def run(
        self,
        stocks: list[StockData],
        sync_state: SyncState,
    ) -> tuple[list[StockData], str]:
        """
        전략 판단과 딥다이브 대상 선정을 수행합니다.

        Returns:
            (final_picks, deep_dive_report_text)
            final_picks: 이번 턴에 새로 보고할 종목 (최대 3개)
        """
        if not stocks:
            return [], ""

        # 1. YAML Manifest에서 전략 자동 로드
        try:
            strategy = get_current_strategy()
        except Exception as e:
            self.log_error(f"전략 로드 실패: {e}")
            return [], ""

        # 2. 전략 실행 (시장 시간 중에만 실제 매수 허용)
        allow_buy = self.ctx.is_market_hours()
        simulation_results = []
        current_cash = 3000000  # 기본값; StrategyEngine에서 가상 계좌 연동 가능

        for s in stocks:
            try:
                decision = strategy.analyze_target(s.to_dict(), {}, {"decision": "APPROVED"}, current_cash)
                s.signal = decision.get('action', 'WATCH')
                simulation_results.append(s)
            except Exception as e:
                self.log_error(f"전략 판단 실패 {s.code}: {e}")
                s.signal = 'WATCH'
                simulation_results.append(s)

        # 3. 중복 방지: 오늘 이미 보고된 종목 제외 (하루 최대 9개)
        reported_codes = [item['code'] for item in sync_state.daily_reported_info]
        new_picks = []

        if len(reported_codes) < 9:
            for s in simulation_results:
                if s.signal in ['BUY', 'WATCH'] and s.code not in reported_codes:
                    new_picks.append(s)
                    if len(reported_codes) + len(new_picks) >= 9:
                        break

        final_picks = new_picks[:3]

        # 4. 신규 보고 종목이 있으면 상태 업데이트 + 엑셀 기록
        if final_picks:
            self.log(f"신규 보고 대상: {[s.name for s in final_picks]}")
            sync_state.daily_reported_info.extend(
                [{'code': s.code, 'name': s.name} for s in final_picks]
            )
            self.storage.save_sync_state(sync_state)
            self.storage.update_monthly_excel(final_picks, self.ctx.now_kst)
        else:
            self.log("신규 보고 종목 없음 (모두 기존 보고 목록에 포함)")

        # 5. 시뮬레이터 주가 동기화 (Registry에서 자동 로드)
        self._run_simulators(stocks)

        return final_picks, simulation_results

    def _run_simulators(self, stocks: list[StockData]) -> None:
        """
        YAML Manifest의 active 시뮬레이터들을 실행합니다.
        새 시뮬레이터 추가 시 이 메서드는 수정하지 않습니다.
        """
        try:
            current_prices = {s.code: s.price for s in stocks if s.price > 0}
            simulators = get_active_simulators()

            self.log(f"시뮬레이터 동기화 시작 ({len(simulators)}개 활성)")
            for sim in simulators:
                try:
                    sim.run(current_prices)
                except Exception as e:
                    self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")

            self.log("시뮬레이터 동기화 완료")
        except Exception as e:
            self.log_error(f"시뮬레이터 전체 실패: {e}")
