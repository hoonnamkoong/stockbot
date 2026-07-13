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


def _median(xs):
    if not xs:
        return 0.0
    s = sorted(xs); n = len(s); m = n // 2
    return float(s[m]) if n % 2 else (s[m - 1] + s[m]) / 2.0


def _adx(series):
    if len(series) < 2:
        return 0.0
    direction = abs(series[-1] - series[0])
    volatility = sum(abs(series[i] - series[i - 1]) for i in range(1, len(series)))
    return (direction / volatility * 100.0) if volatility else 0.0


def libero_action(after_close: bool, market_hours: bool) -> str | None:
    """리베로가 이번 런에서 할 일.

    15:30~15:49는 두 조건이 함께 참이다. 마감 후 확정을 먼저 판정하지 않으면
    EOD 채점이 영영 돌지 않는다 (태스커의 마지막 신호가 15:30이기 때문).
    """
    if after_close:
        return 'finalize'
    if market_hours:
        return 'nowcast'
    return None


class TradeEngineWorker(BaseWorker):
    """
    Stage 3: 전략 판단(BUY/WATCH) + 시뮬레이터 주가 동기화.
    StrategyEngine.execute_simulation()을 통해 전략을 실행합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self._kis_provider = None  # 백필용 KISDataProvider 지연 생성

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

        # 7. 프로그램 매매(실전 계좌 자동 심 운용) — config ON & 유효 시에만 실주문(내부 fail-closed)
        try:
            from src.pipeline.workers.program_trader import run_program_trading
            run_program_trading(
                candidates,
                is_market_hours=self.ctx.is_market_hours(),
                now_kst=self.ctx.now_kst,
                log=self.log,
                log_error=self.log_error,
                enrich=self._enrich_universe,  # 심 전용 유니버스 보강 — 페이퍼 경로와 동일 적용
            )
        except Exception as e:
            self.log_error(f"프로그램 매매 실행 실패(무시하고 계속): {e}")

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

            # 리베로 나우캐스트용 top100 라이브 실측 (실패해도 파이프라인 계속)
            live_breadth = None  # (breadth%, momentum, 표본수, [codes]) | None
            try:
                live_breadth = self._fetch_top100_breadth()
                if live_breadth:
                    self.log(f"  top100 라이브 breadth: {live_breadth[0]:.1f}% (표본 {live_breadth[2]})")
            except Exception as e:
                self.log_error(f"top100 라이브 breadth 수집 실패: {e}")

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
                    is_libero = getattr(sim, 'IS_ANALYZER', False) and sim.__class__.__name__ == 'LiberoSimulator'
                    if is_libero:
                        # 국면 판단의 breadth/momentum/trend를 top100 라이브 실측으로 교체 (버즈 표본 편향 제거)
                        if live_breadth:
                            sim.live_market_metrics = {
                                'breadth': live_breadth[0], 'momentum': live_breadth[1],
                                'trend': self._top100_trend_from_csv(),  # None이면 Sim0가 버즈 ADX로 폴백
                                'sample': live_breadth[2]}
                        else:
                            sim.live_market_metrics = None
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
                    # Libero 나우캐스트: 장중엔 시간당 실측·예측·채점, 마감 후엔 EOD 확정 채점
                    if is_libero:
                        now_kst = self.ctx.now_kst
                        action = libero_action(
                            after_close=self.ctx.is_after_market_close(),
                            market_hours=self.ctx.is_market_hours(),
                        )
                        if action == 'finalize':
                            # 마감 후 라이브 등락률 = 확정 종가 기준. 실패 시 당일 갱신 CSV 폴백.
                            actual_eod = live_breadth[0] if live_breadth else self._get_actual_breadth_from_csv()
                            sim.finalize_eod(actual_eod, now_kst=now_kst)
                        elif action == 'nowcast' and live_breadth:
                            codes = live_breadth[3]
                            sim.update_nowcast(
                                live_breadth[0], now_kst=now_kst,
                                backfill=lambda hhmm: self._backfill_breadth_kis(hhmm, codes))
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

    @staticmethod
    def _breadth_momentum(rates):
        """top100 등락률 리스트 → (breadth%, momentum median). 빈 리스트면 None."""
        if not rates:
            return None
        ups = sum(1 for r in rates if r > 0)
        return round(ups / len(rates) * 100, 1), round(_median(rates), 2)

    def _top100_trend_from_csv(self, csv_path='output/kospi_top100_close.csv', lookback=10):
        """종가 시계열 CSV(wide)에서 종목별 ADX 근사의 median. 실패 시 None."""
        import csv as _csv
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                rows = list(_csv.reader(f))
        except Exception:
            return None
        if len(rows) < 3:
            return None
        header = rows[0]
        data = rows[1:][-lookback:]
        adxs = []
        for col in range(1, len(header)):
            series = []
            for r in data:
                if col < len(r):
                    try:
                        series.append(float(r[col]))
                    except ValueError:
                        pass
            if len(series) >= 2:
                adxs.append(_adx(series))
        return round(_median(adxs), 1) if adxs else None

    def _fetch_top100_breadth(self) -> tuple[float, float, int, list] | None:
        """네이버 시총 페이지에서 KOSPI top100 장중 등락률 → 실측 breadth/momentum.

        fetch_kospi_top100.py와 동일 소스(sise_market_sum). 반환 (breadth, momentum, 표본수, codes).
        표본이 80 미만이면 부분 실패로 보고 None (왜곡된 실측으로 채점 오염 방지).
        """
        import requests
        from bs4 import BeautifulSoup

        naver_hdrs = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://finance.naver.com/',
        }
        codes, rates = [], []
        seen: set = set()
        for page in range(1, 5):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            res = requests.get(url, headers=naver_hdrs, timeout=10)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            table = soup.select_one('table.type_2')
            if not table:
                break
            for row in table.select('tr'):
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                name_tag = cols[1].select_one('a')
                if not name_tag:
                    continue
                code = name_tag['href'].split('code=')[-1]
                if not code.isdigit() or code in seen:
                    continue
                rate_txt = cols[4].get_text(strip=True).replace('%', '').replace(',', '')
                try:
                    rate = float(rate_txt)
                except ValueError:
                    continue
                seen.add(code)
                codes.append(code)
                rates.append(rate)
                if len(codes) >= 100:
                    break
            if len(codes) >= 100:
                break
        if len(codes) < 80:
            return None
        breadth, momentum = self._breadth_momentum(rates)
        return breadth, momentum, len(codes), codes

    def _backfill_breadth_kis(self, hhmm: str, codes: list) -> float | None:
        """KIS 당일분봉으로 특정 시각(HH:MM)의 top100 breadth 복원 — 런 결측 백필 전용.

        종목당 1콜(총 ~100콜, 유량제한 초당 20건 고려 0.06s 간격). 표본 80 미만이면 None.
        """
        import time as _time
        if not codes:
            return None
        if self._kis_provider is None:
            from src.trade.kis_data_provider import KISDataProvider
            self._kis_provider = KISDataProvider()
        hhmmss = hhmm.replace(':', '') + '00'
        self.log(f"  [백필] {hhmm} 시점 breadth 복원 시작 ({len(codes)}종목, KIS 분봉)")
        ups, total = 0, 0
        for code in codes:
            d = self._kis_provider.get_minute_price_at(code, hhmmss)
            if d:
                total += 1
                if d['price'] > d['prev_close']:
                    ups += 1
            _time.sleep(0.06)
        if total < 80:
            self.log_error(f"  [백필] 표본 부족({total}) — 채점 보류")
            return None
        breadth = round(ups / total * 100, 1)
        self.log(f"  [백필] {hhmm} breadth={breadth}% (표본 {total})")
        return breadth

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

