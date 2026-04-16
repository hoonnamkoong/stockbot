"""
[V50.1] Stage 3 Worker: 전략 판단 + 시뮬레이터 (TradeEngineWorker)
=======================================================
실제 engine.py / simulator 인터페이스에 맞게 수정.
- engine.execute_simulation(candidates, allow_buy) 사용
- sim.run(candidates_list, current_prices=dict) 사용
"""

import os
import time
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData, SyncState
from src.data.storage_manager import StorageManager
from src.strategy.registry import get_active_simulators


class TradeEngineWorker(BaseWorker):
    """
    Stage 3: 전략 판단(BUY/WATCH) + 시뮬레이터 주가 동기화.
    StrategyEngine.execute_simulation()을 통해 전략을 실행합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage

    def run(
        self,
        stocks: list[StockData],
        sync_state: SyncState,
    ) -> tuple[list, list]:
        """
        전략 판단과 딥다이브 대상 선정을 수행합니다.

        Returns:
            (final_picks, simulation_results)
            - final_picks: 이번 턴에 새로 보고할 종목 dict 목록 (최대 3개)
            - simulation_results: 전략 판단 결과 전체
        """
        if not stocks:
            return [], []

        # dict 목록으로 변환 (기존 코드 호환)
        candidates = [s.to_dict() for s in stocks]

        # 1. StrategyEngine으로 전략 판단
        try:
            from src.strategy.engine import StrategyEngine
            engine = StrategyEngine()
            allow_buy = self.ctx.is_market_hours()
            simulation_results = engine.execute_simulation(candidates, allow_buy=allow_buy)
            self.log(f"전략 판단 완료: {len(simulation_results)}개 / allow_buy={allow_buy}")
        except Exception as e:
            self.log_error(f"StrategyEngine 실패: {e}")
            # Fallback: 모든 종목을 WATCH로
            simulation_results = [
                {'code': s.code, 'name': s.name, 'signal': 'WATCH', 'reason': 'Engine fallback'}
                for s in stocks
            ]

        # 2. signal 정보를 원본 candidates에 병합
        signal_map = {r['code']: r.get('signal', 'WATCH') for r in simulation_results}
        for c in candidates:
            c['signal'] = signal_map.get(c['code'], 'WATCH')

        # 3. 중복 방지: 오늘 이미 보고된 종목 제외 (하루 최대 9개)
        daily_reported_info = sync_state.daily_reported_info
        reported_codes = [item['code'] for item in daily_reported_info]
        new_picks = []

        if len(reported_codes) < 9:
            for r in simulation_results:
                if r.get('signal') in ['BUY', 'WATCH'] and r['code'] not in reported_codes:
                    # candidates에서 풀 데이터 가져오기
                    full = next((c for c in candidates if c['code'] == r['code']), r)
                    full['signal'] = r.get('signal', 'WATCH')
                    new_picks.append(full)
                    if len(reported_codes) + len(new_picks) >= 9:
                        break

        final_picks = new_picks[:3]
        # 해당 배치 내 순위(rank) 추가: 1~3위
        for i, p in enumerate(final_picks):
            p['rank'] = i + 1

        # 9개 완성 여부 감지
        total_after = len(reported_codes) + len(final_picks)
        sync_state.daily_complete = total_after >= 9

        # 4. 신규 보고 종목이 있으면 상태 업데이트 + 엑셀 기록
        if final_picks:
            formatted_names = [f"{p['name']}({p.get('rank','?')}위)" for p in final_picks]
            self.log(f"신규 보고 대상: {formatted_names}")
            sync_state.daily_reported_info.extend(
                [{'code': p['code'], 'name': p['name'], 'rank': p.get('rank', 0)} for p in final_picks]
            )
            self.storage.save_sync_state(sync_state)

        # 5. 시뮬레이터 3종 실행 (Registry에서 자동 로드)
        self._run_simulators(candidates)

        return final_picks, simulation_results

    def _run_simulators(self, candidates: list[dict]) -> None:
        """
        YAML Manifest의 active 시뮬레이터들을 실행합니다.
        실제 simulator.run(candidates, current_prices=dict) 시그니처 사용.
        [Fix] 포트폴리오 보유 종목 중 오늘 Buzz Filter 이탈 종목의
              현재가를 네이버에서 별도 조회하여 current_prices에 보강합니다.
        """
        try:
            # 1. 오늘 candidates 기반으로 현재가 구성
            current_prices = {
                s['code']: s.get('price', s.get('current_price', 0))
                for s in candidates if s.get('code')
            }
            simulators = get_active_simulators()
            self.log(f"시뮬레이터 동기화 시작 ({len(simulators)}개 활성, {len(current_prices)}개 현재가)")

            # 2. 포트폴리오 종목 중 현재가 미확보된 코드 수집
            missing_codes = set()
            for sim in simulators:
                for code in sim.state.get('portfolio', {}).keys():
                    if code not in current_prices or current_prices[code] == 0:
                        missing_codes.add(code)

            # 3. 미확보 종목 현재가를 네이버에서 조회하여 보강
            if missing_codes:
                self.log(f"  현재가 미확보 {len(missing_codes)}개 종목 네이버 보강 조회")
                extra = self._fetch_portfolio_prices(list(missing_codes))
                current_prices.update(extra)
                self.log(f"  보강 결과: { {k: v for k, v in extra.items()} }")

            for sim in simulators:
                try:
                    sim.run(candidates, current_prices=current_prices)
                    self.log(f"  {sim.__class__.__name__} 완료")
                except Exception as e:
                    self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")

            self.log("시뮬레이터 동기화 완료")
        except Exception as e:
            self.log_error(f"시뮬레이터 전체 실패: {e}")

    def _fetch_portfolio_prices(self, codes: list) -> dict:
        """
        Buzz Filter 이탈 종목의 현재가를 네이버 금융에서 직접 조회합니다.
        DataFetcherWorker._get_stock_details()와 동일한 URL을 사용합니다.
        frgn.naver 페이지의 첫 번째 데이터 행(data_rows[0][1])이 오늘 종가입니다.
        """
        import re
        import requests
        from bs4 import BeautifulSoup

        prices = {}
        for code in codes:
            try:
                url = f"https://finance.naver.com/item/frgn.naver?code={code}"
                res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
                soup = BeautifulSoup(res.content, 'html.parser')
                rows = soup.select('table.type2 tr')
                data_rows = [
                    r.select('td') for r in rows
                    if len(r.select('td')) == 9
                    and re.match(r'\d{4}', r.select('td')[0].get_text(strip=True))
                ]
                if data_rows:
                    price_text = data_rows[0][1].get_text().replace(',', '').strip()
                    prices[code] = int(price_text) if price_text.isdigit() else 0
                    self.log(f"    {code}: {prices[code]:,}원")
            except Exception as e:
                self.log_error(f"    {code} 현재가 조회 실패: {e}")
        return prices

