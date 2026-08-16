"""투자자별 일별 매매동향(개인·외국인·기관)을 적재한다. KIS `FHKST01010900`.

왜 필요한가 (2026-08-17 실측, 30거래일 11,403 종목-일):

    익일 시가→종가(수수료 후)
      외국인 순매수 상위   +0.20% (승률 53%)
      기관 순매수 상위     −0.82% (승률 40%)   ← 역신호
      외인+기관 합산 상위   −0.01% (승률 48%)   ← 서로 죽인다

심2(수급동승)가 합산 순위를 유니버스로 쓰고 있었고, 이 측정으로 외국인 단독으로
바꿨다. 그런데 **그 판단의 근거가 30거래일뿐이다.**

이 TR은 **최근 30거래일만** 준다. 창이 계속 밀려나므로 오늘 안 받으면 오늘 것은
영원히 못 받는다. 6월 데이터를 이미 그렇게 놓쳤다 — 매일 받아 누적해야 한다.

순매수뿐 아니라 매수량·매도량이 따로 온다(`shnu`=매수, `seln`=매도).
체결 방향성(누가 얼마나 사고 파는가)의 일별 근사로 쓸 수 있다.

사용:
    python scripts/fetch_investor_flows.py --universe data/univ.csv -o data/investor_flows.csv
"""
import argparse
import csv
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from scripts.fetch_kis_history import kis  # noqa: E402

FIELDS = ['date', 'code', 'close', 'prsn_net', 'frgn_net', 'orgn_net',
          'prsn_buy', 'frgn_buy', 'orgn_buy', 'prsn_sell', 'frgn_sell', 'orgn_sell']
_MAP = [('prsn_net', 'prsn_ntby_qty'), ('frgn_net', 'frgn_ntby_qty'), ('orgn_net', 'orgn_ntby_qty'),
        ('prsn_buy', 'prsn_shnu_vol'), ('frgn_buy', 'frgn_shnu_vol'), ('orgn_buy', 'orgn_shnu_vol'),
        ('prsn_sell', 'prsn_seln_vol'), ('frgn_sell', 'frgn_seln_vol'), ('orgn_sell', 'orgn_seln_vol')]


def fetch(code):
    d = kis('FHKST01010900', '/uapi/domestic-stock/v1/quotations/inquire-member',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code})
    if d is None:
        return None                      # 실패를 빈 리스트와 구분한다
    out = []
    for x in (d.get('output') or []):
        try:
            row = dict(date=x['stck_bsop_date'], code=code, close=float(x['stck_clpr'] or 0))
            for k, src in _MAP:
                row[k] = float(x.get(src) or 0)
            out.append(row)
        except Exception:
            pass
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--universe', required=True, help='code 컬럼 CSV')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args()

    with open(a.universe, encoding='utf-8-sig') as f:
        codes = [r['code'] for r in csv.DictReader(f)]

    # 기존 파일과 병합(누적). 같은 (date, code)는 새 값으로 덮는다.
    rows = {}
    if os.path.exists(a.out):
        with open(a.out, encoding='utf-8-sig') as f:
            for r in csv.DictReader(f):
                rows[(r['date'], r['code'])] = r
        print(f'기존 {len(rows)}행에 누적')

    fail = []
    for i, code in enumerate(codes):
        got = fetch(code)
        if got is None:
            fail.append(code)
        else:
            for r in got:
                rows[(r['date'], r['code'])] = r
        time.sleep(0.12)
        if (i + 1) % 100 == 0:
            print(f'  {i + 1}/{len(codes)} (누적 {len(rows)}행)', flush=True)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction='ignore')
        w.writeheader()
        for k in sorted(rows):
            w.writerow(rows[k])
    days = sorted({k[0] for k in rows})
    print(f'저장 {a.out} ({len(rows)}행, {len(days)}거래일 {days[0]}~{days[-1]})'
          f'{" | 실패 " + str(len(fail)) + "종목" if fail else ""}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
