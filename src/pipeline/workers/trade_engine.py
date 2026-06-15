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
    ) -> tuple[list, list, dict]:
        """
        전략 판단과 딥다이브 대상 선정을 수행합니다.
        
        Returns:
            (final_picks, simulation_results, sell_candidate)
        """
        if not stocks:
            return [], [], None

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

        # 3. 중복 방지: 당일 이미 딥다이브가 나간 종목 제외
        deep_dived = sync_state.daily_deep_dive_codes
        new_picks = []

        # BUY/WATCH 시그널 중 오늘 딥다이브 안 나간 것 상위 2개 추출
        for r in simulation_results:
            if r.get('signal') in ['BUY', 'WATCH'] and r['code'] not in deep_dived:
                # candidates에서 풀 데이터 가져오기
                full = next((c for c in candidates if c['code'] == r['code']), r).copy()
                full['signal'] = r.get('signal', 'WATCH')
                new_picks.append(full)
                if len(new_picks) >= 2:
                    break

        final_picks = new_picks[:2]
        # 해당 배치 내 순위(rank) 추가: 1~2위
        for i, p in enumerate(final_picks):
            p['rank'] = i + 1

        # 4. 실전 계좌 매도 후보 선정 (정각 텔레그램 타이밍에만)
        sell_candidate = None
        if self.ctx.should_notify():
            try:
                from src.strategy.advisor import StrategyAdvisor
                from src.trade.balance import get_balance
                advisor = StrategyAdvisor()
                balance = get_balance()
                if not balance.get('error'):
                    holdings = balance.get('holdings', [])
                    # 보유 종목 중 오늘 딥다이브 안 나간 것만 대상으로 선정
                    potential_sells = [h for h in holdings if h['code'] not in deep_dived]
                    sell_candidate = advisor.select_sell_candidate(potential_sells)
                    if sell_candidate:
                        self.log(f"매도 추천 후보 선정: {sell_candidate['name']}")
            except Exception as e:
                self.log_error(f"매도 후보 선정 실패: {e}")

        # 5. 신규 보고 종목 상태 기록 - 정각 텔레그램 타이밍에만 수행
        hour = self.ctx.now_kst.hour
        is_morning = hour < 12
        session_name = "오전" if is_morning else "오후"

        if (final_picks or sell_candidate) and self.ctx.should_notify():
            self.log(f"[{session_name} 세션] 신규 보고 대상 상태 기록 (Deep-Dive)")
            
            # 딥다이브 중복 방지 리스트에 추가
            for p in final_picks:
                if p['code'] not in sync_state.daily_deep_dive_codes:
                    sync_state.daily_deep_dive_codes.append(p['code'])
            if sell_candidate and sell_candidate['code'] not in sync_state.daily_deep_dive_codes:
                sync_state.daily_deep_dive_codes.append(sell_candidate['code'])
            
            # 세션별 일반 보고 리스트에도 추가 (기존 대시보드 호환)
            new_items = [{'code': p['code'], 'name': p['name'], 'rank': p.get('rank', 0)} for p in final_picks]
            if is_morning:
                sync_state.morning_reported_info.extend(new_items)
            else:
                sync_state.afternoon_reported_info.extend(new_items)
            
            sync_state.daily_reported_info.extend(new_items)

            # 세션 완료 여부 (9개 기준)
            total_session = len(sync_state.morning_reported_info if is_morning else sync_state.afternoon_reported_info)
            if is_morning:
                sync_state.morning_complete = total_session >= 9
            else:
                sync_state.afternoon_complete = total_session >= 9
            
            self.storage.save_sync_state(sync_state)
        elif final_picks or sell_candidate:
            self.log(f"[{session_name} 세션] 정각 아님 - 종목 상태 기록 생략")

        # 6. 시뮬레이터 3종 실행 (Registry에서 자동 로드)
        self._run_simulators(candidates)

        return final_picks, simulation_results, sell_candidate

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
                    own_universe = sim.get_universe()
                    if own_universe:
                        sim_candidates = self._enrich_universe(own_universe)
                        sim_prices = dict(current_prices)
                        sim_prices.update({
                            s['code']: s.get('price', s.get('current_price', 0))
                            for s in sim_candidates if s.get('price', 0) > 0
                        })
                    else:
                        sim_candidates = candidates
                        sim_prices = current_prices
                    sim.run(sim_candidates, current_prices=sim_prices)
                    self.log(f"  {sim.__class__.__name__} 완료")
                    # Libero 캘리브레이션: run 직후 실제 KOSPI 브레드스 기록
                    if getattr(sim, 'IS_ANALYZER', False) and sim.__class__.__name__ == 'LiberoSimulator':
                        actual_breadth = self._get_actual_breadth_from_csv()
                        if actual_breadth is not None:
                            sim.record_calibration(actual_breadth)
                except Exception as e:
                    self.log_error(f"시뮬레이터 실패 ({sim.__class__.__name__}): {e}")

            self.log("시뮬레이터 동기화 완료")
        except Exception as e:
            self.log_error(f"시뮬레이터 전체 실패: {e}")

    def _enrich_universe(self, stocks: list[dict]) -> list[dict]:
        """
        sim.get_universe() 반환 종목에 sparkline + per/pbr 보강.
        DataFetcher를 거치지 않은 종목이므로 별도 enrichment 필요.
        """
        import re
        import requests
        from bs4 import BeautifulSoup
        from concurrent.futures import ThreadPoolExecutor

        def fetch_sparkline(stock):
            code = stock.get('code', '')
            if not code:
                return stock
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
                    if price_text.isdigit():
                        stock['price'] = int(price_text)
                        stock['current_price'] = stock['price']
                    sparkline = []
                    for row in data_rows[:5]:
                        try:
                            sparkline.append(int(row[1].get_text().replace(',', '').strip()))
                        except Exception:
                            pass
                    if sparkline:
                        stock['sparkline_price'] = sparkline[::-1]  # 오래된→최신 순
                    if len(data_rows) >= 2:
                        stock['foreign_rate'] = float(
                            data_rows[0][8].get_text().replace('%', '').replace(',', '').strip() or 0
                        )
            except Exception:
                pass
            return stock

        with ThreadPoolExecutor(max_workers=10) as ex:
            enriched = list(ex.map(fetch_sparkline, stocks))

        # per/pbr/sector_name + 수급 보강 (Sim3 가치페어, Sim4/4-1 has_inst 조건용)
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis = KISDataProvider()
            for stock in enriched:
                code = stock.get('code', '')
                if not code:
                    continue
                # PER/PBR
                if not (stock.get('per') and stock.get('pbr')):
                    try:
                        quote = kis.get_price_quote(code)
                        for k in ('per', 'pbr', 'sector_name'):
                            if quote.get(k):
                                stock[k] = quote[k]
                    except Exception:
                        pass
                # 수급 — 유니버스 자체에 이미 값이 있으면 덮어쓰지 않음
                if 'frgn_fake_ntby_qty' not in stock or 'orgn_fake_ntby_qty' not in stock:
                    try:
                        trend = kis.get_investor_trend_estimate(code)
                        stock.setdefault('frgn_fake_ntby_qty', trend.get('frgn_fake_ntby_qty', 0))
                        stock.setdefault('orgn_fake_ntby_qty', trend.get('orgn_fake_ntby_qty', 0))
                    except Exception:
                        pass
        except Exception:
            pass

        return enriched

    def _get_actual_breadth_from_csv(self, csv_path: str = 'output/kospi_top100_close.csv') -> float | None:
        """KOSPI top100 CSV의 최근 2행으로 오늘 실제 브레드스(상승 종목 비율%) 산출."""
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                lines = [l for l in f.read().split('\n') if l.strip()]
            if len(lines) < 3:  # 헤더 + 데이터 최소 2행
                return None
            prev_cols = lines[-2].split(',')
            curr_cols = lines[-1].split(',')
            ups, total = 0, 0
            for p_str, c_str in zip(prev_cols[1:], curr_cols[1:]):
                try:
                    p, c = float(p_str.strip()), float(c_str.strip())
                    if p > 0:
                        total += 1
                        if c > p:
                            ups += 1
                except ValueError:
                    continue
            return round(ups / total * 100, 1) if total > 0 else None
        except Exception as e:
            self.log_error(f"KOSPI 브레드스 CSV 산출 실패: {e}")
            return None

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

