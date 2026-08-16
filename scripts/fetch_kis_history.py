"""KIS 과거 시세 수집기 — 백테스트용 일봉/분봉을 CSV로 내린다.

왜 만드는가: 2026-08-15 심1 검증에서 이 수집을 매번 일회성 스크립트로 짰고
세션이 끝나면 사라졌다. 그래서 같은 데이터를 세 번 다시 받았다.

핵심은 **FHKST03010230**(`inquire-time-dailychartprice`)이다. 당일 분봉용
`FHKST03010200`과 다른 TR이고 `src/trade/providers`에 없다. 이 TR을 몰라서
4개월간 심1의 장중 컨셉을 검증하지 못했다. 호출당 최대 120분이라 하루치
(09:00~15:30, 390분)는 4콜이다.

사용:
    # 시총 상위 유니버스 (네이버, 페이지당 50종목)
    PYTHONPATH=. python scripts/fetch_kis_history.py universe --pages 2 -o output/research/univ.csv

    # 일봉
    PYTHONPATH=. python scripts/fetch_kis_history.py daily --universe output/research/univ.csv \
        --from 20260501 --to 20260831 -o output/research/daily.csv

    # 분봉 — (date,code) 쌍 CSV를 받아 그 날짜의 분봉만 받는다
    PYTHONPATH=. python scripts/fetch_kis_history.py minutes --pairs pairs.csv -o out.csv
    # 장 초반만 필요하면 (breadth 계산 등) 1콜로 끝난다
    PYTHONPATH=. python scripts/fetch_kis_history.py minutes --pairs pairs.csv --hours 093000 -o out.csv
"""
import argparse
import csv
import os
import re
import sys
import time

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from src.trade.auth import get_access_token, get_base_url, load_env  # noqa: E402

# 하루치 분봉을 덮는 기준시각 4개. 각 호출은 그 시각 이전 120분을 준다.
FULL_DAY_HOURS = ('153000', '133000', '113000', '093000')
NAVER_HEADERS = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}

_session = {}


def _auth():
    if not _session:
        load_env()
        _session['token'] = get_access_token()
        _session['base'] = get_base_url()
        _session['appkey'] = os.environ.get('KIS_APP_KEY', '').strip()
        _session['appsecret'] = os.environ.get('KIS_APP_SECRET', '').strip()
    return _session


def kis(tr_id, path, params, timeout=10, retries=3):
    """rt_cd가 0이 아니면 None. 실패를 0으로 바꾸지 않는다.

    수천 콜짜리 수집은 중간에 한 번쯤 반드시 타임아웃이 난다. 그때 런 전체가
    죽으면 40분어치가 통째로 사라진다(2026-08-16에 그렇게 잃었다). 그래서
    네트워크 예외는 재시도로 흡수하고, 그래도 안 되면 None으로 넘긴다.
    """
    s = _auth()
    for attempt in range(retries):
        try:
            r = requests.get(
                f"{s['base']}{path}",
                headers={'content-type': 'application/json; charset=utf-8',
                         'authorization': f"Bearer {s['token']}",
                         'appkey': s['appkey'], 'appsecret': s['appsecret'],
                         'tr_id': tr_id, 'custtype': 'P'},
                params=params, timeout=timeout)
            d = r.json()
        except Exception:
            time.sleep(1.5 * (attempt + 1))
            continue
        return d if d.get('rt_cd') == '0' else None
    return None


def cap_universe(sosok, pages):
    """네이버 시총 상위. sosok 0=KOSPI, 1=KOSDAQ. 페이지당 50종목."""
    out = []
    for p in range(1, pages + 1):
        r = requests.get('https://finance.naver.com/sise/sise_market_sum.naver',
                         params={'sosok': sosok, 'page': p},
                         headers=NAVER_HEADERS, timeout=10)
        from bs4 import BeautifulSoup
        s = BeautifulSoup(r.content.decode('euc-kr', 'replace'), 'html.parser')
        t = s.select_one('table.type_2')
        if not t:
            break
        for row in t.select('tr'):
            cells = row.select('td')
            if len(cells) < 5:
                continue
            a = cells[1].select_one('a')
            if not a or 'code=' not in (a.get('href') or ''):
                continue
            code = a['href'].split('code=')[-1]
            if re.fullmatch(r'\d{6}', code):
                out.append((code, a.get_text(strip=True)))
        time.sleep(0.25)
    return out


def daily(code, date_from, date_to):
    """일봉. 실패는 None(빈 리스트와 구분한다)."""
    d = kis('FHKST03010100',
            '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
             'FID_INPUT_DATE_1': date_from, 'FID_INPUT_DATE_2': date_to,
             'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
    if d is None:
        return None
    out = []
    for x in (d.get('output2') or []):
        try:
            out.append(dict(date=x['stck_bsop_date'], code=code,
                            open=float(x['stck_oprc']), high=float(x['stck_hgpr']),
                            low=float(x['stck_lwpr']), close=float(x['stck_clpr']),
                            volume=float(x.get('acml_vol') or 0),
                            amount=float(x.get('acml_tr_pbmn') or 0)))
        except Exception:
            pass
    return out


def minutes(code, date, hours=FULL_DAY_HOURS):
    """과거 분봉(FHKST03010230). 한 콜이라도 실패하면 None.

    ⚠ 이 TR은 요청 시각 이전 120분을 주는데, 그 120분이 **전 거래일로 넘어간다.**
    예) 093000 요청 → 당일 09:00~09:30 31행 + **전일 13:52~15:30 89행**.
    `stck_cntg_hour`만 읽으면 전일 오후가 당일 오후로 둔갑한다. 2026-08-15 세션이
    이걸 놓쳐 청산가(15:19)가 통째로 전일 값이었고, 그 위에 세운 결론 3개를
    폐기했다. **`stck_bsop_date`로 반드시 걸러야 한다.**
    """
    out = {}
    for hh in hours:
        d = kis('FHKST03010230',
                '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice',
                {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
                 'FID_INPUT_DATE_1': date, 'FID_INPUT_HOUR_1': hh,
                 'FID_PW_DATA_INCU_YN': 'Y', 'FID_FAKE_TICK_INCU_YN': 'N'})
        if d is None:
            return None
        for x in (d.get('output2') or []):
            if x.get('stck_bsop_date') != date:
                continue
            try:
                out[x['stck_cntg_hour']] = (float(x['stck_prpr']), float(x['stck_hgpr']),
                                            float(x['stck_lwpr']),
                                            float(x.get('cntg_vol') or 0),
                                            float(x.get('acml_tr_pbmn') or 0))
            except Exception:
                pass
        time.sleep(0.08)
    return sorted(out.items())


def write_csv(path, rows):
    if not rows:
        print('저장할 행이 없다', file=sys.stderr)
        return
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f'저장 {path} ({len(rows)}행)')


def read_universe(path):
    with open(path, encoding='utf-8-sig') as f:
        return [(r['code'], r.get('name', '')) for r in csv.DictReader(f)]


def cmd_universe(a):
    rows = []
    for sosok, label in ((0, 'KOSPI'), (1, 'KOSDAQ')):
        got = cap_universe(sosok, a.pages)
        print(f'{label} 시총상위 {len(got)}종목')
        rows += [dict(code=c, name=n, market=label) for c, n in got]
    write_csv(a.out, rows)


def cmd_daily(a):
    univ = read_universe(a.universe)
    rows, fail = [], []
    for i, (code, name) in enumerate(univ):
        got = daily(code, a.date_from, a.date_to)
        if got is None:
            fail.append(code)
        else:
            for r in got:
                r['name'] = name
                rows.append(r)
        time.sleep(0.12)
        if (i + 1) % 100 == 0:
            print(f'  {i + 1}/{len(univ)}', flush=True)
    print(f'수집 {len(rows)}행, 실패 {len(fail)}종목 {fail[:10]}')
    write_csv(a.out, rows)


def cmd_minutes(a):
    """분봉 수집. 한 쌍씩 즉시 append 한다 — 중간에 죽어도 받은 만큼은 남는다.

    같은 -o로 다시 돌리면 이미 있는 (date,code)는 건너뛴다(이어받기).
    """
    with open(a.pairs, encoding='utf-8-sig') as f:
        pairs = [(r['date'], r['code'], r.get('name', '')) for r in csv.DictReader(f)]
    hours = FULL_DAY_HOURS if a.hours == 'full' else tuple(a.hours.split(','))

    done = set()
    if os.path.exists(a.out):
        with open(a.out, encoding='utf-8-sig') as f:
            done = {(r['date'], r['code']) for r in csv.DictReader(f)}
        print(f'이어받기: 이미 {len(done)}쌍 수집됨')
    todo = [p for p in pairs if (p[0], p[1]) not in done]

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    fields = ['date', 'code', 'name', 'hhmm', 'price', 'high', 'low', 'vol', 'amount']
    n, fail = 0, []
    with open(a.out, 'a', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not done:
            w.writeheader()
        for i, (date, code, name) in enumerate(todo):
            got = minutes(code, date, hours)
            if not got:
                fail.append((date, code))
                continue
            for t, (price, high, low, vol, amount) in got:
                w.writerow(dict(date=date, code=code, name=name, hhmm=t[:4],
                                price=price, high=high, low=low, vol=vol, amount=amount))
                n += 1
            f.flush()
            if (i + 1) % 100 == 0:
                print(f'  {i + 1}/{len(todo)} (누적 {n}행, 실패 {len(fail)})', flush=True)
    print(f'수집 {n}행, 실패 {len(fail)}건 {fail[:5]}')
    print(f'저장 {a.out}')


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    u = sub.add_parser('universe', help='네이버 시총 상위 유니버스')
    u.add_argument('--pages', type=int, default=2, help='시장별 페이지 수(페이지당 50종목)')
    u.add_argument('-o', '--out', required=True)
    u.set_defaults(func=cmd_universe)

    d = sub.add_parser('daily', help='일봉')
    d.add_argument('--universe', required=True)
    d.add_argument('--from', dest='date_from', required=True)
    d.add_argument('--to', dest='date_to', required=True)
    d.add_argument('-o', '--out', required=True)
    d.set_defaults(func=cmd_daily)

    m = sub.add_parser('minutes', help='과거 분봉(FHKST03010230)')
    m.add_argument('--pairs', required=True, help='date,code[,name] 컬럼 CSV')
    m.add_argument('--hours', default='full',
                   help="'full'(하루치 4콜) 또는 기준시각 콤마목록(예: 093000)")
    m.add_argument('-o', '--out', required=True)
    m.set_defaults(func=cmd_minutes)

    a = ap.parse_args()
    a.func(a)


if __name__ == '__main__':
    main()
