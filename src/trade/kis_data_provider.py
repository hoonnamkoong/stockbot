"""
KIS API 데이터 공급자 (KISDataProvider)
================================================
시뮬레이터 고도화를 위한 KIS API 전담 캐시 레이어.
- 5분 캐시(실시간 지표) / 1일 캐시(투자의견) / 7일 캐시(재무비율)
- 모든 API 실패 시 빈 dict 반환 → 기존 시뮬레이터 로직 영향 없음
"""

import os
import time
import requests
from datetime import datetime, timedelta
from typing import Optional


class KISDataProvider:
    # TTL 상수 (초)
    TTL_REALTIME = 300       # 5분 — 투자자 추세, 외인기관 가집계
    TTL_DAILY = 86400        # 1일 — 투자의견, 증권사별 의견
    TTL_FINANCIAL = 604800   # 7일 — 재무비율 (분기 업데이트)

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

    def _get(self, url: str, tr_id: str, params: dict, timeout: int = 5) -> dict:
        if not self._token or not self._base_url:
            return {}
        try:
            r = requests.get(
                f"{self._base_url}{url}",
                headers=self._headers(tr_id),
                params=params,
                timeout=timeout,
            )
            if r.status_code == 200:
                body = r.json()
                if body.get("rt_cd") == "0":
                    return body
        except Exception:
            pass
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
    # 2. 재무 수익성비율 (ROE 등)
    # ──────────────────────────────────────────────────
    def get_finance_profit_ratio(self, code: str) -> dict:
        """
        최근 결산 기준 ROE, 순이익률 반환.
        반환 키: roe, net_profit_rate
        """
        key = f"profit_ratio_{code}"
        cached = self._get_cached(key, self.TTL_FINANCIAL)
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
            self._set_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "roe": self._to_float(row.get("self_cptl_ntin_inrt", 0)),   # 자기자본 순이익률 = ROE
            "net_profit_rate": self._to_float(row.get("sale_ntin_rate", 0)),
        }
        self._set_cache(key, result)
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
        cached = self._get_cached(key, self.TTL_FINANCIAL)
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
            self._set_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "debt_ratio": self._to_float(row.get("lblt_rate", 999)),
            "current_ratio": self._to_float(row.get("crnt_rate", 0)),
        }
        self._set_cache(key, result)
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
        cached = self._get_cached(key, self.TTL_DAILY)
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
            self._set_cache(key, result)
            return result

        row = rows[0] if isinstance(rows, list) else rows
        result = {
            "invest_opinion": row.get("invt_opnn", ""),
            "target_price":   self._to_int(row.get("hts_goal_prc", 0)),
            "opinion_divergence": self._to_float(row.get("dprt", 0)),
        }
        self._set_cache(key, result)
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
        cached = self._get_cached(key, self.TTL_DAILY)
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
            self._set_cache(key, result)
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
        self._set_cache(key, result)
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
        KIS inquire-price(FHKST01010100)로 현재가, PER, PBR, sector_name 반환.
        반환 키: price, change_rate_pct, per, pbr, sector_name
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
            result = {"price": 0, "change_rate_pct": 0.0, "per": 0.0, "pbr": 0.0, "sector_name": ""}
            self._set_cache(key, result)
            return result

        result = {
            "price": self._to_int(out.get("stck_prpr", 0)),
            "change_rate_pct": self._to_float(out.get("prdy_ctrt", 0)),
            "per": self._to_float(out.get("per", 0)),
            "pbr": self._to_float(out.get("pbr", 0)),
            "sector_name": out.get("bstp_kor_isnm", "").strip(),
        }
        self._set_cache(key, result)
        return result

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
        key = f"fluctuation_rank_{market}_{sort}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached

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

        result = []
        for r in rows[:limit]:
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

        self._set_cache(key, result)
        return result

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
        key = f"frgn_inst_rank_{market}_{etc_cls}"
        cached = self._get_cached(key, self.TTL_REALTIME)
        if cached is not None:
            return cached

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

        result = []
        for r in rows[:limit]:
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

        self._set_cache(key, result)
        return result

    # ──────────────────────────────────────────────────
    # 10. 재무비율 수익성 순위 (FHPST01750000)
    # ──────────────────────────────────────────────────
    def get_finance_ratio_rank(self, market: str = '0001', limit: int = 30) -> list[dict]:
        """
        재무비율 수익성 순위 상위 종목 조회 (Sim3 유니버스용).
        반환: [{code, name, price, roe, debt_ratio, amount}, ...]
        """
        key = f"finance_ratio_rank_{market}"
        cached = self._get_cached(key, self.TTL_FINANCIAL)
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

        self._set_cache(key, result)
        return result

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
            return int(str(v).replace(",", "").strip())
        except Exception:
            return 0

    @staticmethod
    def _to_float(v) -> float:
        try:
            return float(str(v).replace(",", "").strip())
        except Exception:
            return 0.0
