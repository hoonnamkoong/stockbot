"""당일 1분봉 수집·병합 — 4분 신호를 10분 격자로 재던 미스매치를 없앤다.

2026-08-08 측정: 게시글 신호는 4분 안에 소멸하고 6분이 넘으면 부호가 뒤집힌다.
그런데 가격은 diag의 10분 격자에만 있어서, 향후 수익률의 상당 부분이 신호와
무관한 구간이다. **표본을 늘리지 않고 검정력을 올리는 유일한 항목이 가격 해상도다.**

KIS 분봉(FHKST03010200)은 당일치만 조회된다 — 과거로 소급할 수 없으므로 마감 후에
그날치를 저장해 둬야 하고, 그래서 이미 마감 후에 도는 eod_data.yml에 붙는다.
한 호출에 30건이 오므로 09:00~15:30(390분)은 30분 간격 앵커로 나눠 받는다.

여기에는 네트워크가 없다. 판정·파싱·병합만 순수 함수로 두어, KIS 없이
시각만 바꿔가며 테스트한다(scrape_gate와 같은 방식).
"""

SESSION_OPEN = '0900'
SESSION_CLOSE = '1530'
ROWS_PER_CALL = 30          # KIS가 한 번에 돌려주는 분봉 수
ANCHOR_STEP_MIN = 30        # ROWS_PER_CALL과 같아야 구간이 안 빈다


def anchor_times() -> list[str]:
    """분봉을 받을 기준 시각들(HHMMSS). 마감에서 개장까지 30분씩 거슬러 올라간다.

    KIS는 지정한 시각 **이전** 30건을 주므로, 마지막 앵커가 09:30보다 늦으면
    개장 30분이 통째로 빈다. 07-29 실측에서 09:05~09:15가 가장 요동치는
    구간이었으므로 거기가 비면 신호 검정 자체가 왜곡된다.
    """
    close = int(SESSION_CLOSE[:2]) * 60 + int(SESSION_CLOSE[2:])
    open_ = int(SESSION_OPEN[:2]) * 60 + int(SESSION_OPEN[2:])
    out = []
    t = close
    while t >= open_ + ANCHOR_STEP_MIN:
        out.append(f'{t // 60:02d}{t % 60:02d}00')
        t -= ANCHOR_STEP_MIN
    out.append(f'{open_ // 60 + (ANCHOR_STEP_MIN // 60):02d}'
               f'{(open_ + ANCHOR_STEP_MIN) % 60:02d}00')
    return list(dict.fromkeys(out))


def parse_rows(body: dict) -> list[dict]:
    """KIS 응답의 output2를 [{'hhmm','price','volume'}]로.

    가격 0인 행은 **버린다.** 0은 '0원'이 아니라 미집계이고, 남겨두면 그 분의
    수익률이 −100%로 계산된다(모르는 값을 지어내지 않는다).
    빈 응답은 예외가 아니라 빈 리스트다 — 휴장·거래정지에서 흔하고, 예외로
    올리면 한 종목 때문에 나머지 수집이 죽는다.
    """
    rows = (body or {}).get('output2') or []
    out = []
    for r in rows:
        try:
            hhmmss = str(r.get('stck_cntg_hour') or '')
            price = int(float(r.get('stck_prpr') or 0))
            if len(hhmmss) < 4 or price <= 0:
                continue
            out.append({'hhmm': hhmmss[:4], 'price': price,
                        'volume': int(float(r.get('cntg_vol') or 0))})
        except (TypeError, ValueError):
            continue
    return out


def merge_bars(*batches) -> list[dict]:
    """여러 호출분을 시각 오름차순으로 합치고 같은 분을 하나로 만든다.

    앵커 구간이 겹치므로 같은 분이 두 번 온다. 중복을 남기면 그 분의 거래량이
    두 배로 보이고, as-of 조인이 1:N이 된다.
    """
    by_min: dict[str, dict] = {}
    for batch in batches:
        for r in batch or []:
            by_min[r['hhmm']] = r
    return [by_min[k] for k in sorted(by_min)]


def codes_for_date(csv_path: str, yyyymmdd: str) -> list[str]:
    """그날 순위 스냅샷에 올랐던 종목코드(중복 제거·정렬).

    1분봉은 이 종목들만 받는다. 전 종목을 받으면 KIS 유량을 태우면서 분석에
    쓰이지도 않는다 — 신호가 순위 차분에서 나오기 때문이다.

    파일이 없으면 빈 리스트다. 순위 스냅샷이 아직 없는 날(최초 배포)에 EOD 잡이
    죽으면 그날 1분봉을 통째로 잃는다.
    """
    import csv as _csv
    out = set()
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            for row in _csv.DictReader(f):
                ts = (row.get('ts') or '')
                code = (row.get('code') or '').strip()
                if code and ts[:10].replace('-', '') == yyyymmdd:
                    out.add(code)
    except FileNotFoundError:
        return []
    except Exception:
        return []
    return sorted(out)
