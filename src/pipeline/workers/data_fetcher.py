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
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData
from src.data.storage_manager import StorageManager
from src.strategy import analyzer


class DataFetcherWorker(BaseWorker):
    """
    Stage 1: 네이버 금융 데이터 수집 및 1차 필터링.
    문턱값(threshold)을 넘은 종목만 다음 Stage로 전달합니다.
    """

    def __init__(self, ctx: PipelineContext, storage: StorageManager):
        super().__init__(ctx)
        self.storage = storage

    def run(self) -> list[StockData]:
        """
        전체 수집 파이프라인을 실행합니다.
        Returns:
            1차 필터를 통과한 StockData 목록
        """
        self.log(f"수집 시작 (임계값: {self.ctx.threshold})")

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

        self.log(f"후보 종목 {len(candidates)}개 분석 시작")

        # 4. 병렬 수집 및 1차 필터링
        results_raw = []
        today_display = self.ctx.today_display

        def process_one(s: dict) -> tuple:
            try:
                d = self._get_stock_details(s['code'])
                s.update(d)
                stats = self._get_discussion_stats(s['code'], today_display)
                count = stats['recent_posts_count']

                if count >= self.ctx.threshold:
                    s['recent_posts_count'] = count
                    posts = sorted(stats['new_posts'], key=lambda x: x['likes'], reverse=True)[:5]
                    for p in posts:
                        p['body'] = self._get_post_body(s['code'], p['nid'])
                    s['posts'] = posts
                    return s, stats['updated_state'], True
                return None, stats['updated_state'], False
            except Exception as e:
                print(f"   [DataFetcher] {s.get('name', '?')} 스킵: {e}")
                return None, None, False

        with ThreadPoolExecutor(max_workers=self.ctx.threshold) as executor:
            futures = list(executor.map(process_one, candidates))

        for res, updated_state, passed in futures:
            if updated_state:
                sync_state.stocks.update(updated_state)
            if passed and res:
                results_raw.append(res)

        # 5. 연속 카운트 갱신
        passed_codes = [s['code'] for s in results_raw]
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

        # 6. 상태 저장
        self.storage.save_sync_state(sync_state)

        # 7. Pydantic 변환 (타입 안전성 확보)
        results: list[StockData] = []
        for s in results_raw:
            try:
                results.append(StockData.from_dict(s))
            except Exception as e:
                print(f"   [DataFetcher] Pydantic 변환 실패 {s.get('code')}: {e}")

        self.log(f"수집 완료: {len(results)}개 종목 통과")
        return results

    # ── 내부 수집 메서드들 (기존 scraper.py에서 이전) ──────────────

    def _get_stock_details(self, code: str) -> dict:
        """네이버 외인비중 페이지에서 수급 데이터를 수집합니다."""
        details = {
            'foreign_rate': 0.0, 'foreign_change': 0.0,
            'foreign_net_buy': 0, 'prev_close': 0, 'prev_foreign_rate': 0.0
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
        except Exception as e:
            print(f"   [DataFetcher] 수급 수집 실패 {code}: {e}")
        return details

    def _get_discussion_stats(self, code: str, today_str: str) -> dict:
        """네이버 토론방에서 오늘 게시글을 전수 스캔합니다."""
        session = requests.Session()
        session.headers.update({'User-Agent': 'Mozilla/5.0'})
        unique_nids = set()
        new_posts = []
        max_pages, chunk_size = 40, 8

        def fetch_page(p_idx):
            url = f"https://finance.naver.com/item/board.naver?code={code}&page={p_idx}"
            try:
                res = session.get(url, timeout=5)
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
            except:
                return [], False

        for start_p in range(1, max_pages + 1, chunk_size):
            chunk = range(start_p, min(start_p + chunk_size, max_pages + 1))
            with ThreadPoolExecutor(max_workers=chunk_size) as ex:
                chunk_res = sorted(
                    [(ex.submit(fetch_page, p), p) for p in chunk],
                    key=lambda x: x[1]
                )
                stop_all = False
                for future, _ in chunk_res:
                    posts, stop = future.result()
                    for p in posts:
                        if p['nid'] not in unique_nids:
                            unique_nids.add(p['nid'])
                            new_posts.append(p)
                    if stop: stop_all = True
                if stop_all: break

        latest_nid = new_posts[0]['nid'] if new_posts else None
        return {
            'recent_posts_count': len(unique_nids),
            'new_posts': new_posts,
            'updated_state': {'cumulative_count': len(unique_nids), 'last_nid': latest_nid}
        }

    def _get_post_body(self, code: str, nid: str) -> str:
        """게시글 본문을 수집합니다."""
        url = f"https://finance.naver.com/item/board_read.naver?code={code}&nid={nid}"
        try:
            res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
            soup = BeautifulSoup(res.content, 'html.parser')
            body = soup.select_one('#body')
            if body: return body.get_text(strip=True)
        except:
            pass
        return ""
