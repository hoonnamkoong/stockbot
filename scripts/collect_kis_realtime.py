"""KIS 실시간(웹소켓)을 적재한다 — 프리마켓과 장중, 둘 다.

왜 필요한가 (2026-08-16 실측): 급등의 수익은 **전부 갭에 있다.** 개장 전 뉴스가
평소 대비 4배로 터지면 갭이 +1.30%로 벌어지고(평소 +0.17%) 시가→종가는 −0.79%다.
즉 뉴스는 급등을 예측하지만(적중 11.2% vs 기저 4.8%) **시가에 사면 이미 늦다.**

갭이 만들어지는 과정을 볼 수 있는 유일한 창이 NXT 프리마켓(08:00~08:50)이다.
그런데 **NXT는 REST 과거 조회가 없다** — `FID_COND_MRKT_DIV_CODE=NX`는 0을 준다.
웹소켓 실시간만 존재한다. **지금부터 적재하지 않으면 영원히 검증할 수 없다.**
(분봉 TR을 4개월간 몰라 심1 검증이 막혔던 것과 같은 구조다.)

## 설계 원칙

- **원본 페이로드를 그대로 남긴다.** 필드 매핑이 틀려도 나중에 복구할 수 있다.
  2026-08-16에 분봉 날짜 필드를 안 읽어 결론 4건을 폐기했다. 같은 실수를 반복하지 않는다.
- **줄마다 flush.** 중간에 죽어도 받은 만큼은 남는다.
- 구독은 KIS 한도(약 41건) 안에서. 기본 30종목 — 급증배수 상위 30이 신호의 92%를 덮는다.

사용:
    # 유니버스를 직접 주고
    PYTHONPATH=. python scripts/collect_nxt_premarket.py --universe out/univ.csv --until 0850

    # 일봉에서 전일 거래대금 급증배수 상위 30을 자동 선정
    PYTHONPATH=. python scripts/collect_nxt_premarket.py --daily output/research/daily400.csv --top 30

## 왜 호가까지 받는가 (2026-08-17 실측)

편향 없는 전수 표본(15거래일 × 394종목)에서 **거래대금·가격만으로는 "계속 갈 관심"과
"곧 식을 관심"이 구분되지 않는다.** 관심 속도 상위 N을 실시간으로 뽑아 상승 중인
것만 골라도 이후 30분이 −0.74~+0.04%로, 24개 조합 전부 수수료를 못 넘었다.
청산 규칙 13종을 붙여도 전부 음수였다.

거래대금은 **이미 체결된 것**(과거)이다. 호가 잔량은 **아직 체결 안 된 매수 의사**
(미래)이고, 체결강도는 그 체결이 매수 호가에서 났는지 매도 호가에서 났는지를 가른다.
셋 다 "이미 가격에 반영됨"의 바깥에 있는 정보다. 그리고 **전부 과거가 없다.**

TR:
    H0STCNT0  KRX 실시간 체결       H0NXCNT0  NXT 실시간 체결
    H0STASP0  KRX 실시간 호가       H0NXASP0  NXT 실시간 호가
    H0NXPGM0  NXT 실시간 프로그램매매

⚠ 구독 한도는 **TR×종목 총합**이 약 41건이다. TR 2개면 종목은 20개까지.
"""
import argparse
import asyncio
import csv
import datetime as dt
import json
import os
import statistics as st
import sys
import time

import requests
import websockets

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from src.trade.auth import get_base_url, load_env  # noqa: E402

WS_URL = 'ws://ops.koreainvestment.com:21000'
MAX_SUBSCRIBE = 40          # KIS 웹소켓 구독 한도(약 41건). 여유를 둔다.


def approval_key():
    load_env()
    r = requests.post(f'{get_base_url()}/oauth2/Approval',
                      headers={'content-type': 'application/json'},
                      data=json.dumps({'grant_type': 'client_credentials',
                                       'appkey': os.environ['KIS_APP_KEY'].strip(),
                                       'secretkey': os.environ['KIS_APP_SECRET'].strip()}),
                      timeout=10)
    r.raise_for_status()
    key = r.json().get('approval_key')
    if not key:
        raise RuntimeError(f'승인키 발급 실패: {r.text[:200]}')
    return key


def top_by_surge(daily_csv, top, lookback=20):
    """전일 종가 기준 거래대금 급증배수 상위 N. 장 마감 후에 확정되는 값이다."""
    by = {}
    with open(daily_csv, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            by.setdefault(r['code'], []).append(r)
    out = []
    for code, rows in by.items():
        rows.sort(key=lambda x: x['date'])
        amts = [float(x['amount'] or 0) for x in rows]
        if len(amts) < lookback + 1 or amts[-1] <= 0:
            continue
        hist = [a for a in amts[-lookback - 1:-1] if a > 0]
        if not hist:
            continue
        out.append((amts[-1] / st.mean(hist), code, rows[-1].get('name', '')))
    out.sort(reverse=True)
    return [(c, n) for _, c, n in out[:top]]


def read_universe(path):
    with open(path, encoding='utf-8-sig') as f:
        return [(r['code'], r.get('name', '')) for r in csv.DictReader(f)]


async def collect(codes, tr_ids, out_path, until_hhmm, key):
    names = dict(codes)
    fields = ['recv_at', 'tr_id', 'code', 'raw']
    exists = os.path.exists(out_path)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    f = open(out_path, 'a', encoding='utf-8-sig', newline='')
    w = csv.DictWriter(f, fieldnames=fields)
    if not exists:
        w.writeheader()

    n = 0
    try:
        async with websockets.connect(WS_URL, ping_interval=None, open_timeout=15) as ws:
            for tr_id in tr_ids:
                for code, _ in codes:
                    await ws.send(json.dumps({
                        'header': {'approval_key': key, 'custtype': 'P',
                                   'tr_type': '1', 'content-type': 'utf-8'},
                        'body': {'input': {'tr_id': tr_id, 'tr_key': code}}}))
                    await asyncio.sleep(0.05)
            print(f'{len(codes)}종목 × {len(tr_ids)}TR = {len(codes)*len(tr_ids)}건 구독 '
                  f'({",".join(tr_ids)}). {until_hhmm}까지 수신.', flush=True)

            while True:
                now = dt.datetime.now().strftime('%H%M')
                if now >= until_hhmm:
                    print(f'{until_hhmm} 도달 — 종료', flush=True)
                    break
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=30)
                except asyncio.TimeoutError:
                    continue

                if msg.startswith('{'):        # 구독 응답/PINGPONG
                    d = json.loads(msg)
                    body = d.get('body') or {}
                    if body.get('msg1') and 'SUBSCRIBE' not in str(body.get('msg1')):
                        print('  [응답]', body.get('msg1'), flush=True)
                    if (d.get('header') or {}).get('tr_id') == 'PINGPONG':
                        await ws.pong(msg)
                    continue

                # 실시간: 암호화플래그|TR|건수|본문(^구분, 건수만큼 반복)
                parts = msg.split('|')
                if len(parts) < 4:
                    continue
                body = parts[3]
                code = body.split('^')[0] if '^' in body else ''
                w.writerow(dict(recv_at=dt.datetime.now().isoformat(timespec='seconds'),
                                tr_id=parts[1], code=code, raw=body))
                n += 1
                if n % 200 == 0:
                    f.flush()
                    print(f'  {n}건 수신', flush=True)
    finally:
        f.flush()
        f.close()
        print(f'총 {n}건 저장 → {out_path}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--universe', help='code[,name] CSV. 없으면 --daily에서 자동 선정')
    ap.add_argument('--daily', default='output/research/daily400.csv')
    ap.add_argument('--top', type=int, default=30, help='급증배수 상위 N종목')
    ap.add_argument('--tr', default='H0NXCNT0', help='콤마로 여러 개. 예: H0STCNT0,H0STASP0')
    ap.add_argument('--start', default='', help='이 시각(HHMM)까지 대기 후 시작. '
                                                'GitHub cron은 발화가 밀리므로 일찍 깨워 여기서 맞춘다')
    ap.add_argument('--until', default='0850', help='이 시각(HHMM)까지 수신')
    ap.add_argument('-o', '--out', default='')
    a = ap.parse_args()

    codes = read_universe(a.universe) if a.universe else top_by_surge(a.daily, a.top)
    if not codes:
        print('유니버스가 비었다', file=sys.stderr)
        return 1
    tr_ids = [t.strip() for t in a.tr.split(',') if t.strip()]
    # 한도는 TR×종목 총합이다. TR을 늘리면 종목을 줄여야 한다.
    codes = codes[:max(1, MAX_SUBSCRIBE // len(tr_ids))]
    print('유니버스:', ', '.join(f'{n or c}' for c, n in codes[:10]),
          f'… (총 {len(codes)})')

    if a.start:
        while dt.datetime.now().strftime('%H%M') < a.start:
            if dt.datetime.now().strftime('%H%M') >= a.until:
                print(f'이미 {a.until} 이후 — 수집 없이 종료', flush=True)
                return 0
            time.sleep(10)
        print(f'{a.start} 도달 — 수집 시작', flush=True)

    out = a.out or os.path.join('data', f'rt_{tr_ids[0]}_{dt.date.today():%Y%m%d}.csv')
    asyncio.run(collect(codes, tr_ids, out, a.until, approval_key()))
    return 0


if __name__ == '__main__':
    sys.exit(main())
