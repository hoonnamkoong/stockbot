"""
[V50] Stage 1 Worker: 데이터 수집기 (DataFetcherWorker)
=======================================================
네이버 금융 토론방을 스캔하여 오늘의 이상급등 종목을 수집합니다.
수집 결과를 Pydantic StockData 객체로 변환하여 타입 안전성을 보장합니다.

기존 scraper.py의 Stage 1 로직을 이 클래스로 이전했습니다.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from src import alerts
from src.data import naver_api
from src.pipeline.context import PipelineContext
from src.pipeline.workers.base_worker import BaseWorker
from src.data.schemas import StockData
from src.data.storage_manager import StorageManager
from src.data import post_archive
from src.strategy import analyzer

# 동시 요청량은 게시글 임계값과 무관해야 한다. 임계값에 묶어두면 오후로 갈수록
# 네이버에 던지는 동시 요청이 늘어 페이지가 타임아웃으로 조용히 유실된다.
STOCK_WORKERS = 8   # 동시에 분석할 종목 수
# 종목당 토론 페이지 상한. 한 페이지가 100글이라 옛 board.naver 40페이지(20글)와
# 같은 800글 상한이다 — 게시글 수 분포를 이관 전후로 같게 둔다.
DISCUSSION_MAX_PAGES = 8
PAGE_RETRIES = 3
PAGE_RETRY_WAIT = 0.5
POST_LIMIT = 30       # 종목당 LLM에 넘길 게시글 수 (공감 상위). 2026-07-28: 5 → 30


def format_failure_reasons(reasons: dict) -> str:
    """실패 이유를 많은 순으로 한 줄에 담는다. 없으면 빈 문자열.

    카운터에 담기기만 하고 로그에 안 나가면 없는 계측과 같다 — 2026-09-08에
    실패율 92%를 보고도 429인지 리셋인지 몰랐던 것이 정확히 그 상태였다.
    """
    return ', '.join(f'{k} {v}' for k, v in
                     sorted(reasons.items(), key=lambda kv: -kv[1]))


# 전량 결손이 이만큼 연속돼야 사람에게 올린다. 스크래퍼는 10분 격자라 3런이면
# 약 30분이다. 1런으로 재면 2026-08-13처럼 러너 하나의 4분짜리 네트워크 사고가
# 사람을 깨우고, 그런 알림이 몇 번 반복되면 정작 몇 주짜리 고장 때 아무도 안 본다.
OUTAGE_ALERT_RUNS = 3


def outage_alert(down: list[tuple[str, str]], streak: int, total: int) -> str | None:
    """전량 결손이 연속으로 이어질 때만, 죽은 필드를 **한 건으로 묶어** 돌려준다.

    일부 결손은 종목 사정(신규상장·거래정지)일 수 있어 로그로 충분하다.
    전량 결손은 측정이 죽었다는 뜻이고, 그건 '신호가 없는 날'과 구분되지 않은 채
    몇 주가 간다 — tick_power가 실제로 그렇게 7~8월 내내 0이었다.

    한 건으로 묶는 이유: per(inquire-price)와 tick_power(inquire-ccnl)는
    엔드포인트가 다르지만 호스트가 같아 **항상 같이** 죽는다. 필드별로 쪼개면
    사고 하나에 사람이 두 번 깨어난다(2026-08-13에 그랬다).
    """
    if total <= 0 or not down or streak < OUTAGE_ALERT_RUNS:
        return None
    names = ', '.join(f for f, _ in down)
    detail = '\n'.join(f"· {f}: {note}" for f, note in down)
    return (f"<b>KIS 지표 전량 결손</b>\n\n"
            f"{names} — 후보 {total}종목 전부에서 값을 얻지 못했습니다"
            f"(연속 {streak}런).\n{detail}\n"
            f"이 값을 쓰는 심은 판단 자체가 불가능하고, 로그에는 '신호 없음'으로 보입니다.")


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

        # KIS 호출은 KISDataProvider 하나로 한다. 예전엔 여기서 토큰을 직접 받아
        # requests로 굴리는 사본이 있었는데, 그 사본에는 rt_cd 검사도 응답 형태
        # 대응도 캐시도 없었다 — 2026-08-12에 그 차이로 두 번 사고가 났다.
        try:
            from src.trade.kis_data_provider import KISDataProvider
            self.kis = KISDataProvider()
        except Exception as e:
            self.kis = None
            self.log_error(f"KIS 클라이언트 초기화 실패: {e} — 시세·체결강도 조회 불가")
        # KISDataProvider는 토큰이 비어도 예외 없이 생성된다(_init_auth가 자체
        # 예외를 삼킨다). 그러면 self.kis는 참이지만 모든 필드가 조용히 0으로
        # 나온다 — 예전 코드가 토큰 공백을 잡던 자리를 여기서 대신 잡는다.
        if self.kis and not getattr(self.kis, '_token', None):
            self.log_error("KIS 토큰이 비었습니다 — 시세·체결강도 조회 불가")

        # 4. 병렬 수집 및 1차 필터링
        results_raw = []
        today_display = self.ctx.today_display

        def process_one(s: dict) -> tuple:
            try:
                # 임계값 판정(게시글 스캔)을 먼저 하고, 통과한 종목만 상세조회(HTTP 3회:
                # frgn.naver·KIS inquire-price·main.naver 호가)한다. 예전엔 순서가
                # 반대라 41종목 전부 상세조회한 뒤 24개를 버렸다 — 통과 못 할 종목의
                # 상세조회는 판정에 쓰이지 않으므로 순수 낭비였다(2026-08-04 실측
                # 72콜/런). 두 조회는 서로 다른 소스(토론방 vs 시세)라 순서를
                # 바꿔도 결과가 갈리지 않는다.
                stats = self._get_discussion_stats(s['code'], today_display)
                count = stats['recent_posts_count']
                pages = (stats['total_pages'], stats['failed_pages'],
                         stats['failure_reasons'])

                status = classify(count, self.ctx.threshold, set(adopted), s['code'])
                if status is None:
                    return None, False, pages

                d = self._get_stock_details(s['code'])
                s.update(d)

                s['recent_posts_count'] = count
                s['unique_posters'] = stats['unique_posters']
                s['total_likes'] = stats['total_likes']
                s['status'] = status
                # 상위 5개로 자르기 전에 당일 전체 제목을 아카이브 큐에 담는다.
                # 열망 사전 검증에는 전수가 필요하고, 여기가 전수가 존재하는
                # 유일한 지점이다.
                self._queue_titles(s, stats['new_posts'])
                if status == '활성':
                    ranked = sorted(stats['new_posts'], key=lambda x: x['likes'], reverse=True)
                    # 상위 5개는 하루 글의 0.3%·공감 총량의 2.0%만 담는다(2026-07-28 실측).
                    # 공감 감쇠가 완만해(1~5위 12.8 → 21~30위 5.4) 5는 근거 없는 컷이었다.
                    # 30으로 올린 근거: 30위까지는 공감 0인 글이 하나도 없다(31위부터 등장).
                    # 본문은 수집하지 않는다. 네이버가 게시글 본문을 iframe(m.stock.naver.com)
                    # 으로 분리했고 그마저 SPA라, requests로는 "로딩중"만 온다. 옛 #body
                    # 셀렉터는 페이지에 존재하지 않는다 — 계측 결과가 0/3,165(0%)였던 이유다.
                    # 매 런 55~70건이 전부 실패했고, 남는 건 그 요청에 쓴 시간뿐이었다.
                    # 소비자(analyzer)는 p.get('body', '')로 읽으므로 키가 없어도 안전하다.
                    s['posts'] = ranked[:POST_LIMIT]
                else:
                    s['posts'] = []
                return s, True, pages
            except Exception as e:
                print(f"   [DataFetcher] {s.get('name', '?')} 스킵: {e}")
                return None, False, (0, 0, {})

        with ThreadPoolExecutor(max_workers=STOCK_WORKERS) as executor:
            futures = list(executor.map(process_one, candidates))

        all_reasons: dict[str, int] = {}
        for res, passed, (pages, failed, reasons) in futures:
            self.ctx.scrape_pages_total += pages
            self.ctx.scrape_pages_failed += failed
            for k, v in (reasons or {}).items():
                all_reasons[k] = all_reasons.get(k, 0) + v
            if passed and res:
                results_raw.append(res)

        if self.ctx.scrape_pages_failed:
            self.log(
                f"페이지 수집 실패 {self.ctx.scrape_pages_failed}/{self.ctx.scrape_pages_total}"
                f" ({self.ctx.scrape_pages_failed / max(self.ctx.scrape_pages_total, 1):.1%})"
                + (f" — {format_failure_reasons(all_reasons)}" if all_reasons else "")
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

        # 6. 상태 저장
        self.storage.save_sync_state(sync_state)

        # 6-1. KIS API 보강 데이터 추가 (외인/기관 추정, 재무비율, 투자의견)
        try:
            from src.trade.kis_data_provider import KISDataProvider
            kis_provider = KISDataProvider()
            results_raw = kis_provider.enrich_batch(results_raw)
            self.log(f"KIS 데이터 보강 완료 ({len(results_raw)}개 종목)")
        except Exception as e:
            self.log_error(f"KIS 데이터 보강 실패 (기존 데이터로 계속): {e}")

        # 시가가 비면 심9는 갭을 계산할 수 없어 조용히 0건이 된다(2026-08-03: 18/18 결손).
        # '신호가 없는 하루'와 '측정하지 못한 하루'는 다르므로 여기서 드러낸다.
        missing_open = sum(1 for s in results_raw if not s.get('open_price'))
        if missing_open:
            self.log_error(f"KIS 시가 결손 {missing_open}/{len(results_raw)}종목 — 심9 갭 판정 불가")

        # [2026-08-04, E9] 상세조회 순서를 임계값 판정 뒤로 옮겼다(위 process_one).
        # 통과 종목의 상세조회 자체는 안 바뀌었어야 한다 — 결손률이 오르면 순서
        # 변경이 아니라 다른 문제(토큰 만료·유량제한 등)를 의심할 근거가 된다.
        total = len(results_raw)
        down: list[tuple[str, str]] = []
        for field, note in (
            ('per', 'Sim3 가치페어 밸류에이션 판정 불가'),
            ('tick_power', '체결강도 판정 불가'),
            ('range_history', 'Sim5 채널 산출 불가'),
            ('amount_history', 'Sim9-1 거래대금 급증 판정 불가'),
        ):
            missing = sum(1 for s in results_raw if not s.get(field))
            if missing:
                self.log_error(f"{field} 결손 {missing}/{total}종목 — {note}")
            if total > 0 and missing == total:
                down.append((field, note))

        # 전량 결손은 로그로 끝내면 안 된다. tick_power가 정확히 그렇게 7~8월
        # 내내 0이었고, 아무도 몰랐다. 다만 **한 런의 결손은 아직 고장이 아니다** —
        # 연속으로 이어질 때만 올린다(OUTAGE_ALERT_RUNS 주석 참고).
        streak = alerts.bump_outage_streak('field_outage', bool(down), log=self.log)
        outage = outage_alert(down, streak, total)
        if outage:
            alerts.send_alert_once('field_outage', outage,
                                   now=self.ctx.now_kst, cooldown_min=180,
                                   log=self.log)

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

        return results

    # ── 내부 수집 메서드들 (기존 scraper.py에서 이전) ──────────────

    def _get_stock_details(self, code: str) -> dict:
        """네이버 일별 수급(외인·기관) 표에서 수급 데이터를 수집합니다."""
        details = {
            'foreign_rate': 0.0, 'foreign_change': 0.0,
            'foreign_net_buy': 0, 'prev_close': 0, 'prev_foreign_rate': 0.0,
            'current_price': 0, 'open_price': 0, 'day_high': 0, 'day_low': 0,
        }
        # [2026-09-11] 옛 item/frgn 표 → 네이버 JSON API(같은 재료, 최신이 앞).
        # 09-10 이관 뒤 옛 표는 302 끝의 빈 페이지였고, 파서는 예외 없이 아무것도 못 읽었다.
        rows = naver_api.investor_trend(code)
        if rows is None:
            print(f"   [DataFetcher] 외인비중 수집 실패 {code}")   # 못 닿았다. 지어내지 않는다.
        elif len(rows) >= 2:
            latest, prev = rows[0], rows[1]
            if latest['foreign_hold_ratio'] is not None and prev['foreign_hold_ratio'] is not None:
                details['foreign_rate'] = latest['foreign_hold_ratio']
                details['foreign_change'] = round(latest['foreign_hold_ratio']
                                                  - prev['foreign_hold_ratio'], 3)
                details['prev_foreign_rate'] = prev['foreign_hold_ratio']
            details['inst_net_buy'] = latest['organ_net'] or 0
            details['foreign_net_buy'] = latest['foreign_net'] or 0
            details['prev_close'] = prev['close']

            # 거래상위에서 빠진 종목은 시세를 여기서만 얻을 수 있다 (첫 행 = 오늘 종가/현재가)
            details['current_price'] = latest['close']

            # [V50.3] sparkline_price: 최근 5영업일 종가 (오래된 날짜부터 최신순으로 정렬)
            # [Sim5] range_history: 최근 20영업일 종가 (채널 산출용). 동일 응답이라 추가 콜 0.
            # [Sim9-1] amount_history: 같은 행의 거래량까지 읽어 거래대금
            # 이력을 만든다. "거래대금 급증"을 종목 자신의 평균 대비로 재려면
            # 기준선이 필요한데, 2026-08-26까지 국내에는 그 이력이 아예 없어서
            # 절대 거래대금의 횡단면 z를 쓰고 있었다(= 대형주 필터로 동작).
            # 같은 응답이라 추가 호출 0이다. 거래량만 빈 행은 거래대금에서만 뺀다.
            closes = [r['close'] for r in rows[:20]]
            amounts = [r['close'] * r['volume'] for r in rows[:20] if r['volume'] is not None]
            details['sparkline_price'] = closes[:5][::-1]
            details['range_history'] = closes[::-1]
            details['amount_history'] = amounts[::-1]

        # KIS 보강. 네이버 파싱과 같은 try에 묶지 않는다 — 2026-08-03에 둘이 한
        # 블록이라 main.naver가 타임아웃 나자 KIS 호출이 실행조차 되지 않았다.
        details['tick_power'] = 0.0
        if getattr(self, 'kis', None):
            try:
                q = self.kis.get_price_quote(code)
                # 0으로 덮어쓰지 않는다. 조회 실패도 0으로 오므로, 덮으면 네이버가
                # 얻어둔 값을 잃는다(2026-08-04 실전 0체결의 형태).
                if q.get('price'):
                    details['price'] = q['price']
                    details['current_price'] = q['price']
                if q.get('change_rate_pct'):
                    r = q['change_rate_pct']
                    details['change_rate'] = f"+{r:.2f}%" if r >= 0 else f"{r:.2f}%"
                for src, dst in (
                    ('foreign_rate', 'foreign_rate'), ('prev_close', 'prev_close'),
                    ('open_price', 'open_price'), ('day_high', 'day_high'),
                    ('day_low', 'day_low'), ('per', 'per'), ('pbr', 'pbr'),
                    ('eps', 'eps'), ('bps', 'bps'), ('w52_hgpr', 'w52_hgpr'),
                    ('w52_lwpr', 'w52_lwpr'), ('mkt_cap', 'mkt_cap'),
                    ('amount', 'amount'), ('volume', 'volume'),
                ):
                    if q.get(src):
                        details[dst] = q[src]
                if q.get('sector_name'):
                    details['sector_name'] = q['sector_name']
            except Exception as e:
                print(f"   [DataFetcher] KIS 시세 보강 실패 {code}: {e}")
            try:
                details['tick_power'] = self.kis.get_tick_power(code)
            except Exception as e:
                print(f"   [DataFetcher] KIS 체결강도 조회 실패 {code}: {e}")

        # 2. 호가 잔량 (매도잔량 합계 / 매수잔량 합계) — 옛 item/main 호가표 → 네이버 JSON API
        quote = naver_api.asking_price(code)
        if quote is None:
            print(f"   [DataFetcher] 미시 데이터(호가) 수집 실패 {code}")
        else:
            ask_v, bid_v = quote['total_sell'], quote['total_buy']
            details['bid_ask_ratio'] = ask_v / bid_v if bid_v > 0 else 1.0

        return details

    def _get_discussion_stats(self, code: str, today_str: str) -> dict:
        """네이버 종목토론에서 오늘 게시글을 전수 스캔합니다.

        [2026-09-11] 옛 board.naver(page=N HTML)가 09-10에 stock.naver.com으로 302되자
        표를 못 찾은 파서가 **'글 0건'을 성공으로** 냈다. 지금은 JSON API의 커서
        페이지를 최신순으로 따라가다 어제 글에 닿으면 멈춘다(src/data/naver_api.py).

        커서라서 다음 페이지를 알려면 앞 페이지 응답이 있어야 한다 — 병렬 스캔은
        불가능하다. 한 페이지가 실패하면 **다음 커서를 모르므로 거기서 멈추고
        실패로 센다.** 2026-09-08의 '못 닿는데 max_pages까지 긁는' 증폭(418→34.7% …
        1473→92.0%)이 구조적으로 생기지 않는다. 실패를 '글 0건'으로 접지 않는다 —
        하류 LLMAnalyzerWorker에 `수집 실패율 초과 → 기록하지 않습니다` 게이트가 있다.

        실패 **이유**는 계속 남긴다(2026-09-08: 이유 없이 횟수만 남아 429·리셋·타임아웃을
        못 가렸다). `target`이 'naver_board'인 이유도 그대로다 — 단건 조회와 차단기를 나눈다.

        today_str: ctx.today_display('YYYY.MM.DD'). API의 작성시각은 'YYYY-MM-DDTHH:MM:SS'다.
        """
        session = naver_api.new_session()
        today_iso = today_str.replace('.', '-')
        unique_nids = set()
        new_posts = []
        total_pages = 0
        failed_pages = 0
        failure_reasons: dict[str, int] = {}

        offset = None
        for _ in range(DISCUSSION_MAX_PAGES):
            reasons: dict[str, int] = {}
            page = naver_api.discussion_page(code, offset, session=session, reasons=reasons)
            total_pages += 1
            if page is None:
                failed_pages += 1
                for reason, n in (reasons or {'unknown': 1}).items():
                    failure_reasons[reason] = failure_reasons.get(reason, 0) + n
                break
            posts, offset = page
            reached_yesterday = False
            for p in posts:
                if not p['written_at'].startswith(today_iso):
                    reached_yesterday = True
                    break
                if p['nid'] not in unique_nids:
                    unique_nids.add(p['nid'])
                    new_posts.append({k: p[k] for k in ('nid', 'title', 'likes', 'writer')})
            if reached_yesterday or not posts or not offset:
                break

        # [Sim8] 고유 작성자 수 — 한 사람의 도배와 다수의 관심을 구분하는 축.
        # writer 키는 여기서 떼어낸다. posts는 엑셀·LLM 프롬프트로 흘러가므로
        # 필요 없는 필드를 실어 보내지 않는다.
        writers = {p.pop('writer', '') for p in new_posts}
        writers.discard('')

        # [Sim1] 당일 전체 글의 공감 총량. 전수 스캔 중이라 추가 비용이 없는데
        # 지금까지는 상위 N개만 남기고 나머지 likes를 버리고 있었다.
        total_likes = sum(int(p.get('likes', 0) or 0) for p in new_posts)

        return {
            'recent_posts_count': len(unique_nids),
            'unique_posters': len(writers),
            'total_likes': total_likes,
            'new_posts': new_posts,
            'total_pages': total_pages,
            'failed_pages': failed_pages,
            'failure_reasons': failure_reasons,
        }

    def _reset_body_stats(self) -> None:
        """본문 수집 성공/실패 카운터를 초기화한다. 스레드풀에서 갱신되므로 락을 둔다."""
        import threading
        self._title_lock = threading.Lock()
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
        with self._title_lock:
            self._title_rows.extend(rows)

