"""
KOSPI 거래대금 상위 100 종목 + 일별 종가 100건 수집
=======================================================
출력: output/kospi_top100_close.csv

실행 전 .env 파일에 다음 항목 필요:
  KIS_APP_KEY=
  KIS_APP_SECRET=...
"""

import os
import sys
import time
import json
import csv
import requests
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 0. 환경변수 로드 ──────────────────────────────────
try:
    from dotenv import load_dotenv
    if Path(".env").exists():
        load_dotenv(".env", override=True)
except ImportError:
    pass

APP_KEY    = os.environ.get("KIS_APP_KEY", "").strip()
APP_SECRET = os.environ.get("KIS_APP_SECRET", "").strip()
BASE_URL   = "https://openapi.koreainvestment.com:9443"

if not APP_KEY or not APP_SECRET:
    print("KIS_APP_KEY / KIS_APP_SECRET 환경변수가 없습니다.")
    sys.exit(1)


# 러너의 일시적 네트워크 장애로 종가 수집 전체가 죽지 않도록 한다.
# 2026-07-10 마감 후 런이 KIS 커넥트 타임아웃 한 번에 실패했다.
NET_RETRIES = 3
NET_BACKOFF_SEC = (5, 15)


def _with_retry(fn, *args, **kwargs):
    last = None
    for attempt in range(NET_RETRIES):
        try:
            return fn(*args, **kwargs)
        except requests.RequestException as e:
            last = e
            print(f"[재시도] 통신 오류 (시도 {attempt + 1}/{NET_RETRIES}): {e}")
            if attempt < NET_RETRIES - 1:
                time.sleep(NET_BACKOFF_SEC[attempt])
    raise last


# ── 1. 토큰 발급 ──────────────────────────────────────
def get_token() -> str:
    cache_path = Path("data/kis_token_cache.json")
    if cache_path.exists():
        try:
            d = json.loads(cache_path.read_text(encoding="utf-8"))
            token = d.get("access_token", "")
            exp   = d.get("expires_at", "")
            if token and exp:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone(timedelta(hours=9)))
                if (exp_dt - datetime.now().astimezone()).total_seconds() > 7200:
                    print(f"[토큰] 캐시 사용 (만료: {exp[:16]})")
                    return token
        except Exception:
            pass

    print("[토큰] 새로 발급 중...")
    r = _with_retry(
        requests.post,
        f"{BASE_URL}/oauth2/tokenP",
        json={"grant_type": "client_credentials", "appkey": APP_KEY, "appsecret": APP_SECRET},
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()
    token = body["access_token"]
    exp   = body.get("access_token_token_expired", "")

    cache_path.parent.mkdir(exist_ok=True)
    cache_path.write_text(
        json.dumps({"access_token": token, "expires_at": exp}, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"[토큰] 발급 완료 (만료: {exp[:16]})")
    return token


# ── 2. 공통 헤더 ─────────────────────────────────────
def headers(tr_id: str, token: str) -> dict:
    return {
        "Content-Type": "application/json; charset=utf-8",
        "authorization": f"Bearer {token}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
    }


# ── 3. KOSPI 시가총액 상위 100 ────────────────────────
def _load_previous_universe() -> list[dict]:
    """직전 실행이 남긴 종가 CSV 헤더에서 종목 구성을 복원한다.

    헤더는 ['date', '005930_삼성전자', ...] 꼴이다. 네이버가 막혔을 때만 쓰는
    폴백이며, 여기서 되살리는 것은 종목 코드·이름뿐이다(시세는 KIS로 새로 받는다).
    """
    path = Path("output/kospi_top100_close.csv")
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8-sig") as f:
            header = next(csv.reader(f), [])
    except OSError:
        return []

    stocks = []
    for col in header[1:]:
        code, _, name = col.partition("_")
        if code.isdigit() and name:
            stocks.append({"code": code, "name": name, "price": "0", "trade_amt": "0"})
    return stocks


def fetch_top100_by_trade_amount(_token: str) -> list[dict]:
    """
    네이버 금융 sise_market_sum 페이지에서 KOSPI 시가총액 상위 100 종목.
    거래대금 순위(sise_quant)는 ETF/ETN이 상위를 독식하므로 시가총액 순위로 대체.
    시가총액 상위는 정상 주식만 포함 — ETF/ETN 필터링 불필요.
    """
    from bs4 import BeautifulSoup

    naver_hdrs = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Referer': 'https://finance.naver.com/',
    }

    results = []
    seen_codes: set = set()
    print("[STEP 1] KOSPI 시가총액 상위 100 종목 수집 중 (네이버 금융)...")
    try:
        for page in range(1, 5):
            url = f"https://finance.naver.com/sise/sise_market_sum.naver?sosok=0&page={page}"
            r = _with_retry(requests.get, url, headers=naver_hdrs, timeout=10)
            soup = BeautifulSoup(r.content.decode('euc-kr', 'replace'), 'html.parser')
            table = soup.select_one('table.type_2')
            if not table:
                break
            new_in_page = 0
            for row in table.select('tr'):
                cols = row.select('td')
                if len(cols) < 5:
                    continue
                name_tag = cols[1].select_one('a')
                if not name_tag:
                    continue
                name = name_tag.get_text(strip=True)
                code = name_tag['href'].split('code=')[-1]
                if not code.isdigit() or code in seen_codes:
                    continue
                seen_codes.add(code)
                price_str = cols[2].get_text(strip=True).replace(',', '')
                price = int(price_str) if price_str.isdigit() else 0
                results.append({"code": code, "name": name, "price": str(price), "trade_amt": "0"})
                new_in_page += 1
                if len(results) >= 100:
                    break
            if len(results) >= 100:
                break
            if new_in_page == 0:
                break
            time.sleep(0.3)
    except requests.RequestException as e:
        # 2026-08-03: 러너에서 네이버 커넥트 타임아웃 3연속으로 EOD 런 전체가 죽었고,
        # 심9-1이 하루 실행되지 않았으며 CSV도 멈췄다. 시총 상위 구성은 하루 사이
        # 거의 바뀌지 않으므로 직전 실행이 남긴 구성으로 계속한다.
        # 복원되는 것은 '어떤 종목을 볼지'뿐이고, 시세는 전부 오늘 KIS 실측이다.
        previous = _load_previous_universe()
        if not previous:
            raise
        print(f"[폴백] 네이버 접속 실패({type(e).__name__}) — 직전 CSV의 {len(previous)}종목으로 진행")
        print("       종목 구성은 전 거래일 기준, OHLCV는 오늘 KIS 실측이다.")
        return previous

    results = results[:100]
    print(f"  → {len(results)}개 종목 수집 완료")
    return results


# ── 4. 종목별 일별 OHLCV 100건 ────────────────────────
def fetch_daily_ohlcv(code: str, token: str, count: int = 100) -> list[dict]:
    """
    KIS 국내주식 기간별 시세 (TR: FHKST03010100)
    최대 100건 반환. count=100이면 1회 호출로 충분.

    같은 응답에 시가·고가·저가·거래량·거래대금이 다 들어 있다. 종가만 쓰고 버리면
    심9-1의 고가 채널·진짜 ATR, 심9의 실제 시가를 영영 못 만든다. 전부 보존한다.
    (추가 API 콜 0 — 이미 하던 호출의 응답을 덜 버리는 것뿐이다.)
    """
    today     = datetime.now().strftime("%Y%m%d")
    start_dt  = (datetime.now() - timedelta(days=200)).strftime("%Y%m%d")  # 여유있게 200일 전

    url = f"{BASE_URL}/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice"
    params = {
        "FID_COND_MRKT_DIV_CODE": "J",
        "FID_INPUT_ISCD": code,
        "FID_INPUT_DATE_1": start_dt,
        "FID_INPUT_DATE_2": today,
        "FID_PERIOD_DIV_CODE": "D",   # 일별
        "FID_ORG_ADJ_PRC": "0",       # 수정주가
    }
    r = _with_retry(requests.get, url, headers=headers("FHKST03010100", token), params=params, timeout=10)
    body = r.json()

    if body.get("rt_cd") != "0":
        return []

    rows = body.get("output2", body.get("output", []))
    if not isinstance(rows, list):
        rows = [rows]

    records = []
    for row in rows:
        date  = row.get("stck_bsop_date", "")
        close = row.get("stck_clpr", "")
        if date and close:
            records.append({
                "date":   date,
                "open":   row.get("stck_oprc", ""),
                "high":   row.get("stck_hgpr", ""),
                "low":    row.get("stck_lwpr", ""),
                "close":  close,
                "volume": row.get("acml_vol", ""),
                "amount": row.get("acml_tr_pbmn", ""),
            })

    # 내림차순(최신→오래된) → 오름차순으로 뒤집기
    records.reverse()
    return records[-count:]  # 최신 100건


# ── 5. 메인 ──────────────────────────────────────────
def main():
    token = get_token()
    stocks = fetch_top100_by_trade_amount(token)

    if not stocks:
        print("[오류] 종목 목록을 가져오지 못했습니다.")
        sys.exit(1)

    # Wide 형태 CSV: 행=날짜, 열=종목코드
    # 먼저 모든 날짜 수집
    all_data: dict[str, dict[str, str]] = {}   # {code: {date: close}}
    all_ohlcv: dict[str, list[dict]] = {}      # {code: [OHLCV 레코드]}
    all_dates: set[str] = set()

    print(f"\n[STEP 2] {len(stocks)}개 종목 OHLCV 수집 중...")
    for i, s in enumerate(stocks, 1):
        code = s["code"]
        records = fetch_daily_ohlcv(code, token, count=100)
        all_ohlcv[code] = records
        all_data[code] = {r["date"]: r["close"] for r in records}
        all_dates.update(all_data[code].keys())

        if i % 10 == 0:
            print(f"  {i}/{len(stocks)} 완료...")
        time.sleep(0.06)  # ~17 req/s (20/s 제한 안전 여유)

    sorted_dates = sorted(all_dates)[-100:]  # 최신 100거래일

    # CSV 저장: 행=날짜, 열=종목
    out_path = Path("output/kospi_top100_close.csv")
    out_path.parent.mkdir(exist_ok=True)

    with out_path.open("w", newline="", encoding="utf-8-sig") as f:
        header = ["date"] + [f"{s['code']}_{s['name']}" for s in stocks]
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        for date in sorted_dates:
            row = {"date": date}
            for s in stocks:
                row[f"{s['code']}_{s['name']}"] = all_data[s["code"]].get(date, "")
            writer.writerow(row)

    print(f"\n[완료] {out_path} 저장 ({len(sorted_dates)}행 × {len(stocks)+1}열)")

    # OHLCV long 형태 CSV: 한 행 = 한 종목의 하루.
    # wide로 만들면 종목당 6열이 되어 600열짜리 표가 된다. 백테스트도 long이 편하다.
    date_set = set(sorted_dates)
    ohlcv_path = Path("output/ohlcv_top100.csv")
    with ohlcv_path.open("w", newline="", encoding="utf-8-sig") as f:
        cols = ["date", "code", "name", "open", "high", "low", "close", "volume", "amount"]
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        n = 0
        for s in stocks:
            for r in all_ohlcv.get(s["code"], []):
                if r["date"] not in date_set:
                    continue
                writer.writerow({"date": r["date"], "code": s["code"], "name": s["name"],
                                 "open": r["open"], "high": r["high"], "low": r["low"],
                                 "close": r["close"], "volume": r["volume"],
                                 "amount": r["amount"]})
                n += 1
    print(f"[완료] {ohlcv_path} 저장 ({n}행)")

    # 요약 출력
    print("\n=== 거래대금 상위 10 ===")
    for i, s in enumerate(stocks[:10], 1):
        amt = int(s["trade_amt"]) if s["trade_amt"].isdigit() else 0
        print(f"  {i:2}. {s['name']}({s['code']})  {amt/1e8:,.0f}억원")


if __name__ == "__main__":
    main()
