"""
KIS API 데이터 공급자 (KISDataProvider)
================================================
시뮬레이터 고도화를 위한 KIS API 전담 캐시 레이어.
- 5분 캐시(실시간 지표) / 1일 캐시(투자의견) / 7일 캐시(재무비율)
- 모든 API 실패 시 빈 dict 반환 → 기존 시뮬레이터 로직 영향 없음
"""

import json
import os
import time
import requests
from datetime import datetime, timedelta
from typing import Optional

# 재무비율·투자의견(TTL_FINANCIAL 7일 / TTL_DAILY 1일) 전용 디스크 캐시 경로.
# 파이프라인 런은 매번 새 프로세스라 인메모리 캐시는 6분짜리 수명으로 끝난다 —
# 10분 주기로 도는데 7일짜리 캐시가 매번 다시 조회됐다(17종목×3콜×40런/일).
# data/ 밑에 두면 scraper.yml의 기존 db-data 왕복(Fetch/Deploy)이 그대로 이 파일을
# 실어 나른다 — 워크플로 변경이 필요 없다(data/*.json을 통째로 커밋·복원한다).
_DISK_CACHE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'kis_financial_cache.json')


class KISDataProvider:
    # TTL 상수 (초)
    TTL_REALTIME = 300       # 5분 — 투자자 추세, 외인기관 가집계
    TTL_DAILY = 86400        # 1일 — 투자의견, 증권사별 의견
    TTL_FINANCIAL = 604800   # 7일 — 재무비율 (분기 업데이트)

    # 유니버스 순위 API(get_fluctuation_rank 등) 전용 클래스 레벨 캐시.
    # Sim4·Sim4-1·Sim10(BULL)·프로그램매매가 매 사이클 같은 (market, sort, limit)
    # 조합을 각자 새 KISDataProvider() 인스턴스로 조회한다 — 인스턴스 캐시(self._cache)는
    # 매번 리셋돼 같은 요청이 최대 4번 나갔다. 클래스 레벨로 올려 프로세스(=파이프라인
    # 런) 수명 동안 공유한다.
    # get_price_quote 등 매매 판단 직전 신선도가 핵심인 호출은 여기 넣지 않는다 —
    # program_trader._price_quote()가 "새 인스턴스 = 캐시 무시"로 5분 묵은 값을 피하는
    # 설계에 기대고 있어(주석 참고), 그 경로를 공유 캐시로 옮기면 드리프트 가드가
    # 오래된 가격을 볼 수 있다.
    _rank_cache: dict[str, tuple[float, list]] = {}

    # 재무비율·투자의견(TTL_FINANCIAL/TTL_DAILY) 전용 디스크 백업 캐시. 클래스 레벨
    # 인메모리 사본 + kis_financial_cache.json 파일로 이중 저장한다 — 인메모리는
    # 같은 프로세스 내 인스턴스 간 공유(_rank_cache와 동일 이유), 파일은 프로세스
    # (=파이프라인 런)를 넘어선 공유(E7)를 담당한다.
    _disk_cache: dict[str, tuple[float, object]] = {}
    _disk_cache_loaded = False

    def __init__(self):
        self._cache: dict[str, tuple[float, dict]] = {}  # key → (ts, data)
        self._token: Optional[str] = None
        self._base_url: Optional[str] = None
        self._app_key: Optional[str] = None
        self._app_secret: Optional[str] = None
        self._init_auth()

    def _init_auth(self):
        try:
            from src.trade.auth import get_access_token, get_base_url
            self._token = get_access_token()
            self._base_url = get_base_url()
            self._app_key = os.environ.get("KIS_APP_KEY", "").strip()
            self._app_secret = os.environ.get("KIS_APP_SECRET", "").strip()
        except Exception as e:
            print(f"[KISDataProvider] 인증 초기화 실패: {e}")

    def _headers(self, tr_id: str) -> dict:
        return {
            "Content-Type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self._token}",
            "appkey": self._app_key,
            "appsecret": self._app_secret,
            "tr_id": tr_id,
        }

    def _get_cached(self, key: str, ttl: float) -> Optional[dict]:
        if key in self._cache:
            ts, data = self._cache[key]
            if time.time() - ts < ttl:
                return data
        return None

    def _set_cache(self, key: str, data: dict):
        self._cache[key] = (time.time(), data)

    def _get_rank_cached(self, key: str, ttl: float) -> Optional[list]:
        """클래스 레벨 유니버스 순위 캐시 조회. 호출자마다 얕은 복사본을 준다 —
        서로 다른 심이 같은 리스트를 공유하면 한 심의 enrichment(_enrich_universe)
        수정이 다른 심에 새어 들어간다."""
        entry = KISDataProvider._rank_cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.time() - ts >= ttl:
            return None
        return [dict(row) for row in data]

    @classmethod
    def _ensure_disk_cache_loaded(cls):
        """프로세스에서 최초 1회만 파일을 읽는다. 실패(파일 없음·손상)는
        빈 캐시로 취급한다 — 다음 API 조회가 채워 넣으면 그만이다."""
        if cls._disk_cache_loaded:
            return
        cls._disk_cache_loaded = True
        try:
            with open(_DISK_CACHE_PATH, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            cls._disk_cache = {k: (float(v[0]), v[1]) for k, v in raw.items()}
        except Exception:
            cls._disk_cache = {}

    def _get_disk_cached(self, key: str, ttl: float):
        """재무비율·투자의견(TTL_FINANCIAL/TTL_DAILY) 전용 — 프로세스를 넘어
        디스크에 남는다. 호출자마다 사본을 준다(리스트 값은 _rank_cache와 같은 이유)."""
        KISDataProvider._ensure_disk_cache_loaded()
        entry = KISDataProvider._disk_cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.time() - ts >= ttl:
            return None
        return [dict(row) for row in data] if isinstance(data, list) else dict(data)

    def _set_disk_cache(self, key: str, data):
        KISDataProvider._ensure_disk_cache_loaded()
        KISDataProvider._disk_cache[key] = (time.time(), data)
        self._persist_disk_cache()

    def _persist_disk_cache(self):
        """쓰기 실패는 조용히 넘어간다 — 캐시는 성능 최적화이지 정합성의
        근거가 아니다. 다음 호출이 API로 재조회하면 그만이다."""
        try:
            os.makedirs(os.path.dirname(_DISK_CACHE_PATH), exist_ok=True)
            serializable = {k: [ts, data] for k, (ts, data) in KISDataProvider._disk_cache.items()}
            with open(_DISK_CACHE_PATH, 'w', encoding='utf-8') as f:
                json.dump(serializable, f, ensure_ascii=False)
        except Exception:
            pass

    def _set_rank_cache(self, key: str, data: list):
        """**자르지 않은 전량**을 넣는다. limit은 캐시 키가 아니라 호출자별
        잘라내기다 — 자른 뒤 캐시하면 limit이 작은 호출자가 먼저 도는 것만으로
        뒤 호출자의 응답이 조용히 줄어든다(2026-08-09: 순위 스냅샷이 200종목을
        요청했는데 앞서 돈 심의 30행 캐시를 받아 코스닥 순위가 170만큼 밀렸다)."""
        KISDataProvider._rank_cache[key] = (time.time(), data)

    # 연결과 응답을 따로 잰다. 하나의 숫자로 묶으면 "연결은 빨리 포기하고
    # 응답은 기다린다"를 동시에 할 수 없다.
    CONNECT_TIMEOUT = 3
    READ_TIMEOUT = 5

    # 연결 계열 실패에 한해 이만큼 던진다(재시도 2회 포함). 2026-08-13에 러너
    # 하나의 egress가 4분간 죽어 KIS 호출 60건이 전부 connect timeout이 났는데,
    # 단발 호출이라 그 런의 per·tick_power가 통째로 사라졌다.
    GET_ATTEMPTS = 3
    RETRY_BACKOFF_SEC = 0.3

    def _get(self, url: str, tr_id: str, params: dict, timeout: int = READ_TIMEOUT) -> dict:
        """실패하면 {}를 돌려준다 — 없는 값을 0으로 지어내지 않는다.

        재시도는 **연결 계열 실패에만** 한다. rt_cd != 0이나 HTTP 500은 서버가
        대답한 것이고, 그걸 다시 던지면 유량제한만 키운다.
        """
        if not self._token or not self._base_url:
            return {}
        for attempt in range(self.GET_ATTEMPTS):
            try:
                r = requests.get(
                    f"{self._base_url}{url}",
                    headers=self._headers(tr_id),
                    params=params,
                    timeout=(self.CONNECT_TIMEOUT, timeout),
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
                if attempt + 1 < self.GET_ATTEMPTS:
                    time.sleep(self.RETRY_BACKOFF_SEC * (attempt + 1))
                    continue
                return {}
            except Exception:
                return {}
            if r.status_code == 200:
                try:
                    body = r.json()
                except Exception:
                    return {}
                if body.get("rt_cd") == "0":
                    return body
            return {}
        return {}

    # ──────────────────────────────────────────────────
    # 1. 투자자 추세 추정 (외인/기관 추정 순매수)
    # ──────────────────────────────────────────────────
    def get_investor_trend_estimate(self, code: str) -> dict:
        """
        실시간 장중 외인/기관 추정 순매수 수량 반환.
        반환 키: frgn_fake_ntby_qty, orgn_fake_ntby_qty, sum_fake_ntby_qty
        """
        key = f"investor_trend_{code}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/investor-trend-estimate",
            "HHPTJ04160200",
            {"MKSC_SHRN_ISCD": code},
        )
        # [Fix] 이 API는 시간대별 가집계를 output2(또는 output1)에 담는다.
        #       다른 API와 달리 단수 output이 아니므로 폴백 탐색한다.
        rows = body.get("output2") or body.get("output1") or body.get("output") or []
        if isinstance(rows, dict):
            rows = [rows]
        if not rows:
            result = {"frgn_fake_ntby_qty": 0, "orgn_fake_ntby_qty": 0, "sum_fake_ntby_qty": 0}
            self._set_cache(key, result)
            return result

        # 최신 시간대(가장 늦은 bsop_hour)의 누적 가집계 사용
        try:
            row = max(rows, key=lambda r: str(r.get("bsop_hour", "")))
        except Exception:
            row = rows[-1]
        result = {
            "frgn_fake_ntby_qty": self._to_int(row.get("frgn_fake_ntby_qty", 0)),
            "orgn_fake_ntby_qty": self._to_int(row.get("orgn_fake_ntby_qty", 0)),
            "sum_fake_ntby_qty":  self._to_int(row.get("sum_fake_ntby_qty", 0)),
        }
        self._set_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 1-1. 당일 분봉 특정 시각 가격 (백필 전용 — 캐시 없음)
    # ──────────────────────────────────────────────────
    def get_minute_price_at(self, code: str, hhmmss: str) -> dict:
        """
        당일 분봉조회(FHKST03010200)로 특정 시각의 체결가와 전일종가를 반환.
        반환: {'price': int, 'prev_close': int} — 실패/데이터 없음 시 빈 dict.
        """
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": hhmmss,
                "FID_PW_DATA_INCU_YN": "Y",
            },
        )
        rows = body.get("output2") or []
        prev_close = self._to_int(body.get("output1", {}).get("stck_prdy_clpr", 0))
        if not rows or prev_close <= 0:
            return {}
        price = self._to_int(rows[0].get("stck_prpr", 0))
        if price <= 0:
            return {}
        return {"price": price, "prev_close": prev_close}

    def get_minute_bars(self, code: str, anchor_hhmmss: str) -> list[dict]:
        """당일 분봉 — anchor 시각 **이전** 30건. [{'hhmm','price','volume'}].

        캐시를 쓰지 않는다: 마감 후 1회성 수집이라 TTL 캐시가 오히려 같은 앵커의
        재조회를 막는다. 파싱·병합은 src/data/minute_bars.py(순수 함수)가 한다.
        """
        from src.data.minute_bars import parse_rows
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice",
            "FHKST03010200",
            {
                "FID_ETC_CLS_CODE": "",
                "FID_COND_MRKT_DIV_CODE": "J",
                "FID_INPUT_ISCD": code,
                "FID_INPUT_HOUR_1": anchor_hhmmss,
                "FID_PW_DATA_INCU_YN": "Y",
            },
        )
        return parse_rows(body)

    # ──────────────────────────────────────────────────
    # 2. 재무 수익성비율 (ROE 등)
    # ──────────────────────────────────────────────────
    def get_finance_profit_ratio(self, code: str) -> dict:
        """
        최근 결산 기준 ROE, 순이익률 반환.
        반환 키: roe, net_profit_rate
        """
        key = f"profit_ratio_{code}"
        cached = self._get_disk_cached(key, self.TTL_FINANCIAL)
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/finance/profit-ratio",
            "FHKST66430400",
            {"FID_INPUT_ISCD": code, "FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J"},
        )
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        if not rows:
            result = {"roe": 0.0, "net_profit_rate": 0.0}
            self._set_disk_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "roe": self._to_float(row.get("self_cptl_ntin_inrt", 0)),   # 자기자본 순이익률 = ROE
            "net_profit_rate": self._to_float(row.get("sale_ntin_rate", 0)),
        }
        self._set_disk_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 2-b. TTM 밸류에이션 (최근 4분기 EPS 기준 PER/PBR)
    # ──────────────────────────────────────────────────
    def get_ttm_valuation(self, code: str, price: float) -> dict:
        """최근 4분기(TTM) EPS와 **최근 분기** BPS로 PER/PBR을 계산한다.

        왜 필요한가 (2026-08-17 실측): `inquire-price`가 주는 `per`/`pbr`은
        **직전 연간 결산** EPS·BPS 기준이라, 실적이 개선된 종목을 비싸게 보이게 한다.

            삼성전자   KIS per 41.82 (EPS 6,564=연간)  vs  TTM 22.19 (EPS 12,372)
            SK하이닉스 KIS per 27.90                   vs  TTM 15.89
            현대차     KIS per 12.82                   vs  TTM 13.97  ← 반대로 낮게

        심3은 "PER이 섹터 평균의 80% 이하 = 저평가"로 진입하는데, 섹터 평균
        (`sector_cache`)은 외부 통계라 TTM 기준이다. 종목만 연간 기준이면
        **실적 개선주는 비싸 보여 걸러지고 정체주가 싸 보여 뽑힌다.**

        분기 재무비율(FHKST66430300, FID_DIV_CLS_CODE='1')은 **연내 누적**으로 온다.
        그래서 TTM = 최근분기누적 + (직전연간 − 직전년도 같은분기 누적).
        삼성전자 검증: 6,993 + (6,564 − 1,186) = 12,371 (네이버 TTM 12,372과 일치).

        실패하면 빈 dict를 준다 — 0으로 채우면 "싸다"로 오판된다.
        """
        key = f"ttm_val_{code}"
        cached = self._get_disk_cached(key, self.TTL_FINANCIAL)
        if cached is None:
            body = self._get(
                "/uapi/domestic-stock/v1/finance/financial-ratio",
                "FHKST66430300",
                {"FID_INPUT_ISCD": code, "FID_DIV_CLS_CODE": "1",
                 "FID_COND_MRKT_DIV_CODE": "J"},
            )
            rows = body.get("output") or body.get("output1") or []
            cached = self._ttm_from_quarters(rows if isinstance(rows, list) else [rows])
            self._set_disk_cache(key, cached)

        eps, bps = cached.get("eps_ttm", 0.0), cached.get("bps", 0.0)
        out = dict(cached)
        out["per_ttm"] = round(price / eps, 2) if eps > 0 and price > 0 else 0.0
        out["pbr_ttm"] = round(price / bps, 2) if bps > 0 and price > 0 else 0.0
        return out

    @staticmethod
    def _ttm_from_quarters(rows: list) -> dict:
        """분기 누적 EPS 목록 → TTM EPS + 최근 BPS. 계산 불가면 0."""
        periods = {}
        for r in rows:
            ym = str(r.get("stac_yymm") or "").strip()
            if len(ym) == 6:
                periods[ym] = r
        if not periods:
            return {"eps_ttm": 0.0, "bps": 0.0}
        latest = max(periods)
        cur = periods[latest]
        eps_cur = KISDataProvider._to_float(cur.get("eps", 0))
        bps = KISDataProvider._to_float(cur.get("bps", 0))

        year, month = int(latest[:4]), latest[4:]
        if month == "12":
            return {"eps_ttm": eps_cur, "bps": bps}      # 이미 연간 누적이다
        prev_fy = periods.get(f"{year - 1}12")
        prev_same = periods.get(f"{year - 1}{month}")
        if not prev_fy or not prev_same:
            return {"eps_ttm": 0.0, "bps": bps}          # 조각이 없으면 만들지 않는다
        eps_ttm = (eps_cur
                   + KISDataProvider._to_float(prev_fy.get("eps", 0))
                   - KISDataProvider._to_float(prev_same.get("eps", 0)))
        return {"eps_ttm": round(eps_ttm, 2), "bps": bps}

    def get_earnings_growth(self, code: str) -> dict:
        """분기 실적(FHKST66430300, get_ttm_valuation과 같은 TR)에서 최근 분기
        EPS 전년동기대비 성장률과 매출증가율(grs)을 뽑는다 — Sim11(미너비니
        SEPA)의 실적 가속 필터 재료다.

        2026-08-20 실측: 이 TR이 분기 30개(7년+)를 주고 grs(매출증가율) 필드도
        이미 포함돼 있다. get_ttm_valuation은 TTM PER 계산에만 쓰고 성장률
        자체는 버리고 있었다.

        반환 키: period(YYYYMM), revenue_growth_yoy, eps_growth_yoy(있으면).
        전년동기 조각이 없거나 그때 EPS가 0 이하(적자) 면 eps_growth_yoy를
        만들지 않는다 — 분모가 나쁜 성장률은 지어낸 숫자보다 결손이 낫다.
        실패는 빈 dict.
        """
        key = f"earnings_growth_{code}"
        cached = self._get_disk_cached(key, self.TTL_FINANCIAL)
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/finance/financial-ratio",
            "FHKST66430300",
            {"FID_INPUT_ISCD": code, "FID_DIV_CLS_CODE": "1",
             "FID_COND_MRKT_DIV_CODE": "J"},
        )
        rows = body.get("output") or body.get("output1") or []
        if not isinstance(rows, list):
            rows = [rows]
        periods = {}
        for r in rows:
            ym = str(r.get("stac_yymm") or "").strip()
            if len(ym) == 6:
                periods[ym] = r

        result: dict = {}
        if periods:
            latest = max(periods)
            year, month = int(latest[:4]), latest[4:]
            cur = periods[latest]
            result["period"] = latest
            result["revenue_growth_yoy"] = self._to_float(cur.get("grs", 0))
            prev_same = periods.get(f"{year - 1}{month}")
            if prev_same:
                eps_prev = self._to_float(prev_same.get("eps", 0))
                if eps_prev > 0:
                    eps_cur = self._to_float(cur.get("eps", 0))
                    result["eps_growth_yoy"] = round((eps_cur - eps_prev) / eps_prev * 100, 2)
        self._set_disk_cache(key, result)
        return result

    def get_daily_history(self, code: str, days: int = 250) -> list[dict]:
        """일별 시세(FHKST03010100) 최근 `days` 거래일, 오래된→최신 순.

        Sim11(미너비니 트렌드 템플릿)의 50/150/200일 이동평균 재료 — 기존
        `range_history`(네이버 frgn, 20일 상한)로는 부족해 KIS 일봉을 직접
        쓴다. 2026-08-20 실측: 한 콜은 최대 100건만 준다(요청 구간과 무관하게
        최신 100건). 여러 콜로 이어 붙이되, 각 콜의 FID_INPUT_DATE_2를 직전
        콜에서 받은 가장 오래된 날짜의 전날로 옮겨가며 페이지네이션한다.

        반환 원소: {'date','open','high','low','close','volume','amount'}.
        디스크 캐시 TTL_DAILY(1일) — 일봉은 그날 하루 안 바뀐다(당일 진행 중인
        봉은 이 TR에 안 잡힌다 — 최근 거래일까지의 확정 봉만 온다).
        실패·결손은 빈 리스트다(있는 만큼만 주고 지어내지 않는다).
        """
        key = f"daily_hist_{code}_{days}"
        cached = self._get_disk_cached(key, self.TTL_DAILY)
        if cached is not None:
            return cached

        all_rows: dict[str, dict] = {}
        end_date = datetime.now().strftime("%Y%m%d")
        for _ in range(3):   # 최대 3콜 ≈ 300거래일. days=250이면 3콜로 충분.
            body = self._get(
                "/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice",
                "FHKST03010100",
                {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code,
                 "FID_INPUT_DATE_1": "19000101", "FID_INPUT_DATE_2": end_date,
                 "FID_PERIOD_DIV_CODE": "D", "FID_ORG_ADJ_PRC": "0"},
            )
            rows = body.get("output2") or []
            new_dates = [r.get("stck_bsop_date") for r in rows
                        if r.get("stck_bsop_date") not in all_rows]
            if not new_dates:
                break
            for r in rows:
                d = r.get("stck_bsop_date")
                if d:
                    all_rows[d] = r
            if len(all_rows) >= days:
                break
            oldest = min(new_dates)
            try:
                end_date = (datetime.strptime(oldest, "%Y%m%d")
                           - timedelta(days=1)).strftime("%Y%m%d")
            except ValueError:
                break

        parsed = []
        for d, r in all_rows.items():
            try:
                parsed.append({
                    "date": d,
                    "open": self._to_float(r.get("stck_oprc", 0)),
                    "high": self._to_float(r.get("stck_hgpr", 0)),
                    "low": self._to_float(r.get("stck_lwpr", 0)),
                    "close": self._to_float(r.get("stck_clpr", 0)),
                    "volume": self._to_float(r.get("acml_vol", 0)),
                    "amount": self._to_float(r.get("acml_tr_pbmn", 0)),
                })
            except (KeyError, ValueError):
                continue
        parsed.sort(key=lambda x: x["date"])
        result = parsed[-days:]
        self._set_disk_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 3. 재무 안정성비율 (부채비율 등)
    # ──────────────────────────────────────────────────
    def get_finance_stability_ratio(self, code: str) -> dict:
        """
        최근 결산 기준 부채비율, 유동비율 반환.
        반환 키: debt_ratio, current_ratio
        """
        key = f"stability_ratio_{code}"
        cached = self._get_disk_cached(key, self.TTL_FINANCIAL)
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/finance/stability-ratio",
            "FHKST66430600",
            {"FID_INPUT_ISCD": code, "FID_DIV_CLS_CODE": "0", "FID_COND_MRKT_DIV_CODE": "J"},
        )
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        if not rows:
            result = {"debt_ratio": 999.0, "current_ratio": 0.0}
            self._set_disk_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "debt_ratio": self._to_float(row.get("lblt_rate", 999)),
            "current_ratio": self._to_float(row.get("crnt_rate", 0)),
        }
        self._set_disk_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 4. 종목 투자의견 + 목표가
    # ──────────────────────────────────────────────────
    def get_invest_opinion(self, code: str) -> dict:
        """
        최신 애널리스트 투자의견, HTS 목표가, 목표가 괴리율 반환.
        반환 키: invest_opinion, target_price, opinion_divergence
        """
        key = f"invest_opinion_{code}"
        cached = self._get_disk_cached(key, self.TTL_DAILY)
        if cached is not None:
            return cached

        # [Fix] 종목투자의견 API는 조회기간(FID_INPUT_DATE_1/2)이 필수 → 누락 시 빈 응답
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/invest-opinion",
            "FHKST663300C0",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16633", "FID_INPUT_ISCD": code,
             "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": today},
        )
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        if not rows:
            result = {"invest_opinion": "", "target_price": 0, "opinion_divergence": 0.0}
            self._set_disk_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "invest_opinion": row.get("invt_opnn", ""),
            "target_price":   self._to_int(row.get("hts_goal_prc", 0)),
            "opinion_divergence": self._to_float(row.get("dprt", 0)),
        }
        self._set_disk_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 5. 증권사별 투자의견 요약
    # ──────────────────────────────────────────────────
    def get_invest_opbysec(self, code: str) -> dict:
        """
        증권사별 투자의견을 집계하여 컨센서스 요약 반환.
        반환 키: consensus_buy_count, consensus_avg_target, consensus_summary
        """
        key = f"opbysec_{code}"
        cached = self._get_disk_cached(key, self.TTL_DAILY)
        if cached is not None:
            return cached

        # [Fix] 증권사별 투자의견 API도 조회기간(FID_INPUT_DATE_1/2)이 필수
        today = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=365)).strftime("%Y%m%d")
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/invest-opbysec",
            "FHKST663400C0",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_COND_SCR_DIV_CODE": "16634", "FID_INPUT_ISCD": code,
             "FID_INPUT_DATE_1": start, "FID_INPUT_DATE_2": today},
        )
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        if not rows:
            result = {"consensus_buy_count": 0, "consensus_avg_target": 0, "consensus_summary": ""}
            self._set_disk_cache(key, result)
            return result

        if not isinstance(rows, list):
            rows = [rows]

        buy_count = 0
        targets = []
        firms = []
        for row in rows:
            opnn = row.get("invt_opnn", "")
            tp = self._to_int(row.get("hts_goal_prc", 0))
            firm = row.get("hts_kor_isnm", "")
            if opnn in ("매수", "강력매수", "BUY", "Strong Buy"):
                buy_count += 1
            if tp > 0:
                targets.append(tp)
            if firm:
                firms.append(firm)

        avg_target = int(sum(targets) / len(targets)) if targets else 0
        summary = f"매수의견 {buy_count}/{len(rows)}개사, 평균목표가 {avg_target:,}원" if avg_target else ""

        result = {
            "consensus_buy_count": buy_count,
            "consensus_avg_target": avg_target,
            "consensus_summary": summary,
        }
        self._set_disk_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 6. 종목 뉴스 타이틀
    # ──────────────────────────────────────────────────
    def get_news_titles(self, code: str, limit: int = 7) -> list[str]:
        """
        KIS 뉴스 타이틀 API로 종목 관련 최근 뉴스 제목 반환.
        출처(news_ofer_entp_code)별 1건만 선택해 동일 이벤트 중복 방지.
        TR ID: FHKST01011800
        """
        return [item["title"] for item in self.get_news_items(code, limit)]

    def get_news_items(self, code: str, limit: int = 7) -> list[dict]:
        """
        KIS 뉴스 타이틀 API로 종목 관련 최근 뉴스 제목 + URL 반환.
        출처(news_ofer_entp_code)별 1건만 선택해 동일 이벤트 중복 방지.
        반환 키: title, url (url 없으면 빈 문자열)
        TR ID: FHKST01011800
        """
        key = f"news_items_{code}"
        cached = self._get_cached(key, 1800)  # 30분 캐시
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/news-title",
            "FHKST01011800",
            {
                "FID_NEWS_OFER_ENTP_CODE": "",
                "FID_COND_MRKT_CLS_CODE": "",
                "FID_INPUT_ISCD": code,
                "FID_TITL_CNTT": "",
                "FID_INPUT_DATE_1": "",
                "FID_INPUT_HOUR_1": "",
                "FID_RANK_SORT_CLS_CODE": "",
                "FID_INPUT_SRNO": "",
            },
        )
        rows = body.get("output") or body.get("output1") or body.get("output2") or []
        if not rows:
            self._set_cache(key, [])
            return []

        if not isinstance(rows, list):
            rows = [rows]

        seen_sources: set = set()
        items: list[dict] = []
        for r in rows:
            src = r.get("news_ofer_entp_code", "")
            title = r.get("hts_pbnt_titl_cntt", "").strip()
            url = r.get("hts_pbnt_url", r.get("news_url", r.get("data_src_url", ""))).strip()
            if title and src not in seen_sources:
                seen_sources.add(src)
                items.append({"title": title, "url": url})
            if len(items) >= limit:
                break

        self._set_cache(key, items)
        return items

    # ──────────────────────────────────────────────────
    # 7. 개별 종목 시세/밸류에이션 (PER, PBR, sector_name)
    # ──────────────────────────────────────────────────
    def get_price_quote(self, code: str) -> dict:
        """
        KIS inquire-price(FHKST01010100)로 현재가, PER, PBR, sector_name, 52주 고저 반환.
        반환 키: price, change_rate_pct, per, pbr, sector_name, w52_hgpr, w52_lwpr,
                open_price, day_high, day_low, prev_close

        52주 고저는 같은 응답에 이미 들어 있는데 버리고 있었다 — Sim8의 앵커 판정
        재료라 추가 콜 없이 함께 돌려준다.

        [Sim9] open_price/day_high/day_low/prev_close도 같은 응답 블록이다 — 추가 콜 0.
        Sim9가 버즈 유니버스 대신 이 API로 자체 유니버스를 쓰게 되면서(2026-08-05)
        필요해졌다. data_fetcher._get_stock_details가 같은 필드를 이미 파싱하고
        있었는데(버즈 경로 전용), 이 함수는 그걸 몰라서 버리고 있었다.
        """
        key = f"price_quote_{code}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-price",
            "FHKST01010100",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
        )
        out = body.get("output", {})
        if not out:
            result = {"price": 0, "change_rate_pct": 0.0, "per": 0.0, "pbr": 0.0,
                      "sector_name": "", "w52_hgpr": 0, "w52_lwpr": 0,
                      "open_price": 0, "day_high": 0, "day_low": 0, "prev_close": 0,
                      "foreign_rate": 0.0, "eps": 0, "bps": 0,
                      "mkt_cap": 0, "amount": 0, "volume": 0}
            self._set_cache(key, result)
            return result

        result = {
            "price": self._to_int(out.get("stck_prpr", 0)),
            "change_rate_pct": self._to_float(out.get("prdy_ctrt", 0)),
            "per": self._to_float(out.get("per", 0)),
            "pbr": self._to_float(out.get("pbr", 0)),
            "sector_name": out.get("bstp_kor_isnm", "").strip(),
            "w52_hgpr": self._to_int(out.get("w52_hgpr", 0)),
            "w52_lwpr": self._to_int(out.get("w52_lwpr", 0)),
            "open_price": self._to_int(out.get("stck_oprc", 0)),
            "day_high": self._to_int(out.get("stck_hgpr", 0)),
            "day_low": self._to_int(out.get("stck_lwpr", 0)),
            "prev_close": self._to_int(out.get("stck_sdpr", 0)),
            "foreign_rate": self._to_float(out.get("hts_frgn_ehrt", 0)),
            "eps": self._to_int(float(self._to_float(out.get("eps", 0)))),
            "bps": self._to_int(float(self._to_float(out.get("bps", 0)))),
            "mkt_cap": self._to_int(out.get("hts_avls", 0)),
            "amount": self._to_int(out.get("acml_tr_pbmn", 0)),
            "volume": self._to_int(out.get("acml_vol", 0)),
        }
        self._set_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 7-b. 체결강도 (FHKST01010300 — 주식현재가 체결)
    # ──────────────────────────────────────────────────
    def get_tick_power(self, code: str, timeout: int | None = None) -> float:
        """당일 체결강도(tday_rltv). 얻지 못하면 0.0.

        `timeout`: 이 조회는 2분 매매 루프 안에서 종목당 1콜씩 돈다. 기본
        read 타임아웃(5초)에 재시도 2회까지 겹치면 종목당 최악 10초라, 30종목
        3배치면 30초가 더 붙어 `LOOP_BUDGET_SEC=85`의 "두 바퀴" 조건(첫 바퀴
        25초)을 깬다. 호출부가 더 짧게 줄 수 있게 열어 둔다 — 체결강도는
        게이트 재료라 못 얻으면 매수를 막을 뿐, 늦어서 사이클을 통째로
        날리는 것보다 낫다.

        이 응답의 output은 dict가 아니라 **체결 내역 리스트**다(실호출 확인: 30행,
        최신순). tday_rltv는 당일 누적값이라 모든 행이 같으므로 최신 행만 본다.
        inquire-price(FHKST01010100)에는 이 필드가 없다 — 2026-08-11에 그걸 몰라
        전 종목 결손이 났다.
        """
        key = f"tick_power_{code}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached['value']

        kw = {'timeout': timeout} if timeout else {}
        body = self._get(
            "/uapi/domestic-stock/v1/quotations/inquire-ccnl",
            "FHKST01010300",
            {"FID_COND_MRKT_DIV_CODE": "J", "FID_INPUT_ISCD": code},
            **kw,
        )
        rows = body.get("output") or []
        if isinstance(rows, dict):
            rows = [rows]
        value = self._to_float(rows[0].get("tday_rltv", 0)) if rows else 0.0
        self._set_cache(key, {'value': value})
        return value

    # ──────────────────────────────────────────────────
    # 8. 등락률 순위 (FHPST01700000)
    # ──────────────────────────────────────────────────
    def get_fluctuation_rank(self, market: str = '0001', sort: str = '0', limit: int = 30) -> list[dict]:
        """
        등락률 순위 조회.
        market: '0000'=전체, '0001'=코스피, '1001'=코스닥
        sort: '0'=상승률, '1'=하락률
        반환: [{code, name, price, change_rate, acml_vol, amount}, ...]
        """
        # limit은 키에 넣지 않는다. 순위 API는 몇 종목을 가져오든 호출이 1번이므로
        # (본문에서 전량을 파싱해 캐시한다) limit별로 키를 나누면 같은 응답을 두 번
        # 받게 되고, "추가 API 호출 0"이라는 순위 스냅샷의 전제가 깨진다.
        key = f"fluctuation_rank_{market}_{sort}"
        cached = self._get_rank_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached[:limit]

        body = self._get(
            "/uapi/domestic-stock/v1/ranking/fluctuation",
            "FHPST01700000",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_cond_scr_div_code": "20170",
                "fid_input_iscd": market,
                "fid_rank_sort_cls_code": sort,
                "fid_input_cnt_1": "0",
                "fid_prc_cls_code": "1",
                "fid_input_price_1": "",
                "fid_input_price_2": "",
                "fid_vol_cnt": "",
                "fid_trgt_cls_code": "0",
                "fid_trgt_exls_cls_code": "0",
                "fid_div_cls_code": "0",
                "fid_rsfl_rate1": "",
                "fid_rsfl_rate2": "",
            },
        )
        rows = body.get("output") or []
        if not isinstance(rows, list):
            rows = [rows] if rows else []

        # **자르기 전에** 캐시한다. limit은 캐시 키가 아니다(아래 _set_rank_cache
        # 주석 참고) — 자른 뒤 캐시하면 먼저 도는 심(limit=30)이 뒤에 오는
        # 순위 스냅샷(limit=200)의 응답을 잘라먹는다.
        result = []
        for r in rows:
            code = r.get("stck_shrn_iscd", "").strip()
            if not code:
                continue
            price = self._to_int(r.get("stck_prpr", 0))
            vol = self._to_int(r.get("acml_vol", 0))
            rate = self._to_float(r.get("prdy_ctrt", 0))
            result.append({
                "code": code,
                "name": r.get("hts_kor_isnm", "").strip(),
                "price": price,
                "current_price": price,
                "change_rate": f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%",
                "acml_vol": vol,
                "amount": price * vol,
            })

        self._set_rank_cache(key, result)
        # 방금 만든 result도 캐시가 참조하는 바로 그 리스트다 — 이 호출자에게도
        # 복사본을 줘야 뒤이어 도는 다른 심의 enrichment가 이 심의 사본을 오염시키지 않는다.
        return [dict(row) for row in result[:limit]]

    # ──────────────────────────────────────────────────
    # 9. 외국인/기관 순매수 상위 (FHPTJ04400000)
    # ──────────────────────────────────────────────────
    def get_foreign_institution_rank(self, market: str = '0001', etc_cls: str = '0', limit: int = 30) -> list[dict]:
        """
        외국인/기관 순매수 상위 종목 조회.
        market: '0000'=전체, '0001'=코스피, '1001'=코스닥
        etc_cls: '0'=전체, '1'=외국인, '2'=기관
        반환: [{code, name, price, frgn_fake_ntby_qty, orgn_fake_ntby_qty, amount}, ...]
        """
        key = f"frgn_inst_rank_{market}_{etc_cls}"   # limit은 키가 아니다(위와 같은 이유)
        cached = self._get_rank_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached[:limit]

        body = self._get(
            "/uapi/domestic-stock/v1/quotations/foreign-institution-total",
            "FHPTJ04400000",
            {
                "FID_COND_MRKT_DIV_CODE": "V",
                "FID_COND_SCR_DIV_CODE": "16449",
                "FID_INPUT_ISCD": market,
                "FID_DIV_CLS_CODE": "0",
                "FID_RANK_SORT_CLS_CODE": "0",
                "FID_ETC_CLS_CODE": etc_cls,
            },
        )
        rows = body.get("output") or []
        if not isinstance(rows, list):
            rows = [rows] if rows else []

        # 자르기 전에 캐시한다 — 이유는 get_fluctuation_rank와 같다.
        result = []
        for r in rows:
            code = r.get("mksc_shrn_iscd", "").strip()
            if not code:
                continue
            price = self._to_int(r.get("stck_prpr", 0))
            vol = self._to_int(r.get("acml_vol", 0))
            rate = self._to_float(r.get("prdy_ctrt", 0))
            frgn = self._to_int(r.get("frgn_ntby_qty", 0))
            orgn = self._to_int(r.get("orgn_ntby_qty", r.get("ntby_qty", 0)))
            result.append({
                "code": code,
                "name": r.get("hts_kor_isnm", "").strip(),
                "price": price,
                "current_price": price,
                "change_rate": f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%",
                "acml_vol": vol,
                "amount": price * vol,
                "frgn_fake_ntby_qty": frgn,
                "orgn_fake_ntby_qty": orgn,
            })

        self._set_rank_cache(key, result)
        # 방금 만든 result도 캐시가 참조하는 바로 그 리스트다 — 이 호출자에게도
        # 복사본을 줘야 뒤이어 도는 다른 심의 enrichment가 이 심의 사본을 오염시키지 않는다.
        return [dict(row) for row in result[:limit]]

    # ──────────────────────────────────────────────────
    # 10. 재무비율 수익성 순위 (FHPST01750000)
    # ──────────────────────────────────────────────────
    def get_finance_ratio_rank(self, market: str = '0001', limit: int = 30) -> list[dict]:
        """
        재무비율 수익성 순위 상위 종목 조회 (Sim3 유니버스용).
        반환: [{code, name, price, roe, debt_ratio, amount}, ...]
        """
        key = f"finance_ratio_rank_{market}"
        # TTL_FINANCIAL(7일)이라 인메모리(_rank_cache)가 아니라 디스크 캐시를 쓴다(E7) —
        # 나머지 랭킹(TTL_REALTIME 5분)은 프로세스 수명 안에서만 의미 있지만, 이건
        # 파이프라인 런(프로세스)을 몇 번이고 넘어 살아야 한다.
        cached = self._get_disk_cached(key, self.TTL_FINANCIAL)
        if cached is not None:
            return cached

        year = str(datetime.now().year - 1)
        body = self._get(
            "/uapi/domestic-stock/v1/ranking/finance-ratio",
            "FHPST01750000",
            {
                "fid_cond_mrkt_div_code": "J",
                "fid_cond_scr_div_code": "20175",
                "fid_input_iscd": market,
                "fid_div_cls_code": "0",
                "fid_input_price_1": "",
                "fid_input_price_2": "",
                "fid_vol_cnt": "",
                "fid_input_option_1": year,
                "fid_input_option_2": "3",
                "fid_rank_sort_cls_code": "7",
                "fid_blng_cls_code": "0",
                "fid_trgt_cls_code": "0",
                "fid_trgt_exls_cls_code": "0",
            },
        )
        rows = body.get("output") or []
        if not isinstance(rows, list):
            rows = [rows] if rows else []

        result = []
        for r in rows[:limit]:
            code = r.get("mksc_shrn_iscd", r.get("stck_shrn_iscd", "")).strip()
            if not code:
                continue
            price = self._to_int(r.get("stck_prpr", 0))
            vol = self._to_int(r.get("acml_vol", 0))
            rate = self._to_float(r.get("prdy_ctrt", 0))
            result.append({
                "code": code,
                "name": r.get("hts_kor_isnm", "").strip(),
                "price": price,
                "current_price": price,
                "change_rate": f"+{rate:.2f}%" if rate >= 0 else f"{rate:.2f}%",
                "acml_vol": vol,
                "amount": price * vol,
                "roe": self._to_float(r.get("cptl_ntin_rate", 0)),
                "debt_ratio": self._to_float(r.get("lblt_rate", 999)),
            })

        self._set_disk_cache(key, result)
        # 방금 만든 result도 캐시가 참조하는 바로 그 리스트다 — 이 호출자에게도
        # 복사본을 줘야 뒤이어 도는 다른 심의 enrichment가 이 심의 사본을 오염시키지 않는다.
        return [dict(row) for row in result]

    # ──────────────────────────────────────────────────
    # 배치 enrichment (DataFetcher에서 호출)
    # ──────────────────────────────────────────────────
    def enrich_batch(self, candidates: list[dict]) -> list[dict]:
        """
        candidates 목록 전체에 KIS 데이터를 병합하여 반환.
        API 실패 시 원본 데이터 그대로 유지 (graceful degradation).
        """
        if not self._token:
            return candidates

        for stock in candidates:
            code = stock.get("code", "")
            if not code:
                continue
            try:
                trend = self.get_investor_trend_estimate(code)
                stock.update(trend)
            except Exception:
                pass
            try:
                profit = self.get_finance_profit_ratio(code)
                stock.update(profit)
            except Exception:
                pass
            try:
                stability = self.get_finance_stability_ratio(code)
                stock.update(stability)
            except Exception:
                pass
            try:
                opinion = self.get_invest_opinion(code)
                stock.update(opinion)
            except Exception:
                pass
            try:
                opbysec = self.get_invest_opbysec(code)
                stock.update(opbysec)
            except Exception:
                pass

        return candidates

    # ──────────────────────────────────────────────────
    # 유틸
    # ──────────────────────────────────────────────────
    @staticmethod
    def _to_int(v) -> int:
        try:
            # float 값이 들어오면 직접 변환 (문자열 변환 시 "1500.0" 형태가 되어 int() 실패)
            if isinstance(v, float):
                return int(v)
            return int(str(v).replace(",", "").strip())
        except Exception:
            return 0

    @staticmethod
    def _to_float(v) -> float:
        try:
            return float(str(v).replace(",", "").strip())
        except Exception:
            return 0.0
