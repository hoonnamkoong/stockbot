"""
[V50] Stage 1 Worker: 데이터 수집기 (DataFetcherWorker)
=======================================================
네이버 금융 토론방을 스캔하여 오늘의 이상급등 종목을 수집합니다.
수집 결과를 Pydantic StockData 객체로 변환하여 타입 안전성을 보장합니다.

기존 scraper.py의 Stage 1 로직을 이 클래스로 이전했습니다.
"""

import re
import requests
import os
import time
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData
from src.data.storage_manager import StorageManager
from src.data import usage_log
from src.data import post_archive
from src.strategy import analyzer

# 동시 요청량은 게시글 임계값과 무관해야 한다. 임계값에 묶어두면 오후로 갈수록
# 네이버에 던지는 동시 요청이 늘어 페이지가 타임아웃으로 조용히 유실된다.
STOCK_WORKERS = 8   # 동시에 분석할 종목 수
PAGE_WORKERS = 8    # 종목당 동시에 긁을 토론방 페이지 수
PAGE_RETRIES = 3
PAGE_RETRY_WAIT = 0.5


def classify(count: int, threshold: int, adopted: set, code: str = '') -> str | None:
    """임계값은 신규 채택 기준으로만 쓴다. 이미 채택된 종목은 미달이어도 추적한다."""
    if count >= threshold:
        return '활성'
    if code in adopted:
        return '추적'
    return None


def merge_universe(trending: list[dict], adopted: dict) -> list[dict]:
    """거래량 상위(trending)에 당일 채택 종목(adopted) 중 빠진 것을 뒤에 덧붙인다."""
    known = {c['code'] for c in trending}
    merged = list(trending)
    for code, info in adopted.items():
        if code not in known:
            merged.append({'code': code, 'name': info.get('name', ''),
                           'market': info.get('market', '')})
    return merged


class DataFetcherWorker(BaseWorker):
    """
    Stage 1: 네이버 금융 데이터 수집 및 1차 필터링.
    문턱값(threshold)을 넘은 종목만 다음 Stage로 전달합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage
        self._reset_body_stats()

    def run(self) -> list[StockData]:
        """
        전체 수집 파이프라인을 실행합니다.
        Returns:
            1차 필터를 통과한 StockData 목록
        """
        self.log(f"수집 시작 (임계값: {self.ctx.threshold})")

        # 업종 PER/PBR 기준값 초기화 (no-op, 하드코딩 테이블)
        try:
            from src.data.sector_cache import SectorCache
            SectorCache().ensure_fresh()
        except Exception as e:
            self.log_error(f"업종 캐시 초기화 실패 (계속 진행): {e}")

        # 1. GitHub에서 이전 상태 동기화
        sync_files = self.storage.get_sync_files_list(self.ctx.now_kst)
        self.storage.sync_from_github(sync_files)

        # 2. 상태 로드
        sync_state, _ = self.storage.load_sync_state(self.ctx.today_str)

        # 3. 후보 종목 수집 (KOSPI + KOSDAQ)
        try:
            candidates = (
                analyzer.get_top_trending_stocks('KOSPI') +
                analyzer.get_top_trending_stocks('KOSDAQ')
            )
        except Exception as e:
            self.log_error(f"후보 종목 수집 실패: {e}")
            return []

        # 3-1. 당일 채택 종목 합집합: 거래량 상위에서 빠졌어도 오늘 이미 채택된 종목은 유니버스에 유지
        from src.data import adopted_registry
        adopted = adopted_registry.load(self.ctx.today_str)
        candidates = merge_universe(candidates, adopted)
        self.log(f"유니버스 {len(candidates)}개 (당일 채택 {len(adopted)}개 포함)")

        self.log(f"후보 종목 {len(candidates)}개 분석 시작")

        # [V61.0] KIS API 토큰 사전 발급 (체결강도 조회용)
        try:
            from src.trade.auth import get_access_token, get_base_url
            import os
            self.kis_token = get_access_token()
            self.kis_base_url = get_base_url()
            self.kis_app_key = os.environ.get("KIS_APP_KEY", "").strip().replace("\n", "")
            self.kis_app_secret = os.environ.get("KIS_APP_SECRET", "").strip().replace("\n", "")
        except Exception as e:
            self.log_error(f"KIS API 초기화 실패: {e}")
            self.kis_token = None

        # 4. 병렬 수집 및 1차 필터링
        results_raw = []
        today_display = self.ctx.today_display

        def process_one(s: dict) -> tuple:
            try:
                d = self._get_stock_details(s['code'])
                s.update(d)
                stats = self._get_discussion_stats(s['code'], today_display)
                count = stats['recent_posts_count']
                pages = (stats['total_pages'], stats['failed_pages'])

                status = classify(count, self.ctx.threshold, set(adopted), s['code'])
                if status is None:
                    return None, False, pages

                s['recent_posts_count'] = count
                s['status'] = status
                # 상위 5개로 자르기 전에 당일 전체 제목을 아카이브 큐에 담는다.
                # 열망 사전 검증에는 전수가 필요하고, 여기가 전수가 존재하는
                # 유일한 지점이다.
                self._queue_titles(s, stats['new_posts'])
                if status == '활성':
                    posts = sorted(stats['new_posts'], key=lambda x: x['likes'], reverse=True)[:5]
                    for p in posts:
                        p['body'] = self._get_post_body(s['code'], p['nid'])
                    s['posts'] = posts
                else:
                    s['posts'] = []
                return s, True, pages
            except Exception as e:
                print(f"   [DataFetcher] {s.get('name', '?')} 스킵: {e}")
                return None, False, (0, 0)

        with ThreadPoolExecutor(max_workers=STOCK_WORKERS) as executor:
            futures = list(executor.map(process_one, candidates))

        for res, passed, (pages, failed) in futures:
            self.ctx.scrape_pages_total += pages
            self.ctx.scrape_pages_failed += failed
            if passed and res:
                results_raw.append(res)

        if self.ctx.scrape_pages_failed:
            self.log(
                f"페이지 수집 실패 {self.ctx.scrape_pages_failed}/{self.ctx.scrape_pages_total}"
                f" ({self.ctx.scrape_pages_failed / max(self.ctx.scrape_pages_total, 1):.1%})"
            )

        # 5. 연속 카운트 갱신 (추적 종목은 임계값 미달이므로 연속일수에 포함하지 않는다)
        passed_codes = [s['code'] for s in results_raw if s.get('status') == '활성']
        counts = self.storage.update_consecutive_counts(passed_codes, self.ctx.now_kst)
        for s in results_raw:
            s['consecutive_days'] = counts.get(s['code'], 1)
            # [Bug 4 Fix] change_rate 계산: 등락률을 문자열로 생성
            price = int(s.get('price', s.get('current_price', 0)))
            prev_close = int(s.get('prev_close', 0))
            if prev_close > 0 and price > 0:
                rate = ((price - prev_close) / prev_close) * 100
                s['change_rate'] = f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%"
            elif 'change_rate' not in s:
                s['change_rate'] = "0.00%"

        # 6. 시장 지수 상태 수집 및 상태 저장 (Consensus 반영)
        indices = self._get_market_indices()
        sync_state.market_index_healthy = indices['KOSPI_healthy'] and indices['KOSDAQ_healthy']
        self.storage.save_sync_state(sync_state)

        # 6-1. KIS API 보강 데이터 추가 (외인/기관 추정, 재무비율, 투자의견)
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis_provider = KISDataProvider()
            results_raw = kis_provider.enrich_batch(results_raw)
            self.log(f"KIS 데이터 보강 완료 ({len(results_raw)}개 종목)")
        except Exception as e:
            self.log_error(f"KIS 데이터 보강 실패 (기존 데이터로 계속): {e}")

        # 7. Pydantic 변환 (타입 안전성 확보)
        results: list[StockData] = []
        for s in results_raw:
            try:
                results.append(StockData.from_dict(s))
            except Exception as e:
                print(f"   [DataFetcher] Pydantic 변환 실패 {s.get('code')}: {e}")

        self.log(f"수집 완료: {len(results)}개 종목 통과")
        added = post_archive.append(self._title_rows)
        self.log(f"제목 아카이브: 신규 {added}건 / 수집 {len(self._title_rows)}건")
        usage_log.append({
            'event': 'run_summary',
            'body_ok': self.body_ok,
            'body_fail': self.body_fail,
        })
        return results

    # ── 내부 수집 메서드들 (기존 scraper.py에서 이전) ──────────────

    def _get_stock_details(self, code: str) -> dict:
        """네이버 외인비중 페이지에서 수급 데이터를 수집합니다."""
        details = {
            'foreign_rate': 0.0, 'foreign_change': 0.0,
            'foreign_net_buy': 0, 'prev_close': 0, 'prev_foreign_rate': 0.0,
            'current_price': 0,
        }
        url = f"https://finance.naver.com/item/frgn.naver?code={code}"
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup = BeautifulSoup(res.content, 'html.parser')
            rows = soup.select('table.type2 tr')
            data_rows = [
                r.select('td') for r in rows
                if len(r.select('td')) == 9 and re.match(r'\d{4}', r.select('td')[0].get_text(strip=True))
            ]
            if len(data_rows) >= 2:
                details['foreign_rate'] = float(data_rows[0][8].get_text().replace('%', '').replace(',', '').strip())
                prev_rate = float(data_rows[1][8].get_text().replace('%', '').replace(',', '').strip())
                details['foreign_change'] = round(details['foreign_rate'] - prev_rate, 3)
                details['inst_net_buy'] = int((data_rows[0][5].get_text().replace(',', '').replace('+', '').strip()) or 0)
                details['foreign_net_buy'] = int((data_rows[0][6].get_text().replace(',', '').replace('+', '').strip()) or 0)
                details['prev_close'] = int((data_rows[1][1].get_text().replace(',', '').strip()) or 0)
                details['prev_foreign_rate'] = prev_rate

                # 거래상위에서 빠진 종목은 시세를 여기서만 얻을 수 있다 (표 첫 행 = 오늘 종가/현재가)
                details['current_price'] = int(data_rows[0][1].get_text().replace(',', '').strip() or 0)

                # [V50.3] sparkline_price: 최근 5영업일 종가 (오래된 날짜부터 최신순으로 정렬)
                # [Sim5] range_history: 최근 20영업일 종가 (채널 산출용). 동일 페이지라 추가 콜 0.
                closes = []
                for r in data_rows[:20]:
                    try:
                        closes.append(int(r[1].get_text().replace(',', '').strip()))
                    except:
                        pass
                details['sparkline_price'] = closes[:5][::-1]
                details['range_history'] = closes[::-1]
        except Exception as e:
            print(f"   [DataFetcher] 외인비중 수집 실패 {code}: {e}")

        # [V60.0] 체결강도 및 호가잔량 추출을 위해 메인 페이지 추가 파싱
        try:
            main_url = f"https://finance.naver.com/item/main.naver?code={code}"
            main_res = requests.get(main_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            main_soup = BeautifulSoup(main_res.content, 'html.parser')
            
            # 1. 체결강도 추출 (KIS API 활용, 네이버 제공 중단에 따른 대응)
            details['tick_power'] = 0.0
            if getattr(self, 'kis_token', None) and getattr(self, 'kis_app_key', None):
                try:
                    url = f"{self.kis_base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
                    headers = {
                        "Content-Type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {self.kis_token}",
                        "appkey": self.kis_app_key,
                        "appsecret": self.kis_app_secret,
                        "tr_id": "FHKST01010100"
                    }
                    params = {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code}
                    # 잦은 호출 방지를 위해 timeout 짧게 설정
                    r = requests.get(url, headers=headers, params=params, timeout=3)
                    if r.status_code == 200:
                        out = r.json().get('output', {})
                        # 체결강도
                        if out.get('tday_rltv'):
                            details['tick_power'] = float(out['tday_rltv'])
                        # 기존 Naver 데이터 KIS로 보강 (더 정확)
                        if out.get('stck_prpr'):
                            details['price'] = int(out['stck_prpr'])
                            details['current_price'] = int(out['stck_prpr'])
                        if out.get('prdy_ctrt'):
                            rate = float(out['prdy_ctrt'])
                            details['change_rate'] = f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%"
                        if out.get('hts_frgn_ehrt'):
                            details['foreign_rate'] = float(out['hts_frgn_ehrt'])
                        if out.get('stck_sdpr'):
                            details['prev_close'] = int(out['stck_sdpr'])
                        # 신규 밸류에이션/52주 필드 (추가 API 호출 없이 동일 응답에서 파싱)
                        for _f in ('per', 'pbr'):
                            if out.get(_f):
                                try: details[_f] = float(out[_f])
                                except (ValueError, TypeError): pass
                        for _f in ('eps', 'bps', 'w52_hgpr', 'w52_lwpr'):
                            if out.get(_f):
                                try: details[_f] = int(float(out[_f]))
                                except (ValueError, TypeError): pass
                        if out.get('hts_avls'):
                            try: details['mkt_cap'] = int(out['hts_avls'])
                            except (ValueError, TypeError): pass
                        # 거래대금/거래량: KIS가 네이버보다 정확 (원 단위)
                        if out.get('acml_tr_pbmn'):
                            try: details['amount'] = int(out['acml_tr_pbmn'])
                            except (ValueError, TypeError): pass
                        if out.get('acml_vol'):
                            try: details['volume'] = int(out['acml_vol'])
                            except (ValueError, TypeError): pass
                        if out.get('bstp_kor_isnm'):
                            details['sector_name'] = out['bstp_kor_isnm'].strip()
                except Exception as e:
                    pass
            
            # 2. 호가 잔량 추출 (매도잔량 / 매수잔량)
            # 메인 페이지의 호가 정보 테이블 탐색
            quote_table = main_soup.select_one("table.type2.type_stock2")
            if quote_table:
                # 보통 매도잔량은 상단 합계, 매수잔량은 하단 합계에 위치
                ask_total = quote_table.select_one("tr.total td.sell") # 매도잔량 합계
                bid_total = quote_table.select_one("tr.total td.buy")  # 매수잔량 합계
                if ask_total and bid_total:
                    ask_v = int(ask_total.get_text().replace(',', '').strip() or 1)
                    bid_v = int(bid_total.get_text().replace(',', '').strip() or 1)
                    details['bid_ask_ratio'] = ask_v / bid_v if bid_v > 0 else 1.0
        except Exception as e:
            print(f"   [DataFetcher] 미시 데이터(체결/호가) 수집 실패 {code}: {e}")

        return details

    def _get_market_indices(self) -> dict:
        """[V60.0] KOSPI, KOSDAQ 지수 상태를 수집합니다."""
        url = "https://finance.naver.com/sise/sise_index.naver?code=KOSPI"
        indices = {'KOSPI_healthy': True, 'KOSDAQ_healthy': True}
        try:
            # 코스피
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup = BeautifulSoup(res.content, 'html.parser')
            # 지수 등락 확인 (상승/보합이면 healthy로 간주)
            kospi_change = soup.select_one("#now_value")
            # (간소화: 전일 대비 하락폭이 2% 이상이면 unhealthy)
            indices['KOSPI_healthy'] = True # 실시간 로직은 실제 등락률 파싱 필요
        except:
            pass
        return indices

    def _get_discussion_stats(self, code: str, today_str: str) -> dict:
        """네이버 토론방에서 오늘 게시글을 전수 스캔합니다."""
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        unique_nids = set()
        new_posts = []
        max_pages, chunk_size = 40, PAGE_WORKERS
        total_pages = 0
        failed_pages = 0

        def parse_page(res):
            soup = BeautifulSoup(res.content, 'html.parser')
            posts, stop = [], False
            for row in soup.select('table.type2 tr'):
                cols = row.select('td')
                if len(cols) < 5: continue
                if today_str not in cols[0].get_text(strip=True):
                    stop = True; break
                tag = row.select_one('td.title a')
                if not tag: continue
                nid = re.search(r'nid=(\d+)', tag['href'])
                if not nid: continue
                try: likes = int(cols[4].get_text(strip=True))
                except: likes = 0
                posts.append({'nid': nid.group(1), 'title': tag.get_text(strip=True), 'likes': likes})
            return posts, stop

        def fetch_page(p_idx):
            """(posts, stop, ok). 실패한 페이지를 '글 0건'으로 반환하면 게시글 수가 조용히 깎인다."""
            url = f"https://finance.naver.com/item/board.naver?code={code}&page={p_idx}"
            for attempt in range(PAGE_RETRIES):
                try:
                    res = session.get(url, timeout=5)
                    if res.status_code != 200:
                        raise requests.HTTPError(f"HTTP {res.status_code}")
                    posts, stop = parse_page(res)
                    return posts, stop, True
                except requests.RequestException:
                    if attempt < PAGE_RETRIES - 1:
                        time.sleep(PAGE_RETRY_WAIT * (attempt + 1))
            return [], False, False

        for start_p in range(1, max_pages + 1, chunk_size):
            chunk = range(start_p, min(start_p + chunk_size, max_pages + 1))
            with ThreadPoolExecutor(max_workers=chunk_size) as ex:
                chunk_res = sorted(
                    [(ex.submit(fetch_page, p), p) for p in chunk],
                    key=lambda x: x[1]
                )
                stop_all = False
                for future, _ in chunk_res:
                    posts, stop, ok = future.result()
                    total_pages += 1
                    if not ok:
                        failed_pages += 1
                    for p in posts:
                        if p['nid'] not in unique_nids:
                            unique_nids.add(p['nid'])
                            new_posts.append(p)
                    if stop: stop_all = True
                if stop_all: break

        return {
            'recent_posts_count': len(unique_nids),
            'new_posts': new_posts,
            'total_pages': total_pages,
            'failed_pages': failed_pages,
        }

    def _reset_body_stats(self) -> None:
        """본문 수집 성공/실패 카운터를 초기화한다. 스레드풀에서 갱신되므로 락을 둔다."""
        import threading
        self.body_ok = 0
        self.body_fail = 0
        self._body_lock = threading.Lock()
        self._title_rows = []

    def _queue_titles(self, stock: dict, new_posts: list) -> None:
        """당일 전체 게시글 제목을 아카이브 큐에 담는다.

        여기서 바로 파일에 쓰지 않는 이유: process_one이 스레드풀에서 돌아
        동시 append가 CSV를 깨뜨린다. run() 끝에서 한 번에 flush한다.
        """
        rows = [{
            'date': self.ctx.today_str,
            'code': stock.get('code', ''),
            'name': stock.get('name', ''),
            'nid': p.get('nid', ''),
            'title': p.get('title', ''),
            'likes': p.get('likes', 0),
        } for p in (new_posts or [])]
        if not rows:
            return
        with self._body_lock:
            self._title_rows.extend(rows)

    def _get_post_body(self, code: str, nid: str) -> str:
        """게시글 본문을 수집합니다.

        성공/실패를 센다. Gemini 프롬프트에 본문이 실제로 실리는 비율을 모르면
        '본문을 줄여 표본을 늘릴지'를 판단할 수 없다. 실패해도 ""를 반환하므로
        호출부에서는 구분이 안 된다.
        """
        url = f"https://finance.naver.com/item/board_read.naver?code={code}&nid={nid}"
        text = ""
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup = BeautifulSoup(res.content, 'html.parser')
            body = soup.select_one('#body')
            if body:
                text = body.get_text(strip=True)
        except:
            pass

        with self._body_lock:
            if text:
                self.body_ok += 1
            else:
                self.body_fail += 1
        return text
