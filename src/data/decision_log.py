# -*- coding: utf-8 -*-
"""사이클마다 **모든 심의 결정**을 한 파일에 남긴다 (이관 3단계 그림자 운전의 재료).

## 왜 심별 diag가 아니라 단일 파일인가

`sim_diag`는 심별로 `<sim>_diag_<날짜>.csv`를 쓴다. 그 방식을 전 심으로 넓히면
**손으로 맞춰야 하는 목록이 둘 늘어난다**:

    scripts/trade_loop.py  DIAG_LOG_SIM_IDS          (파이썬 dict)
    .github/workflows/scraper.yml
        sim6_diag_*.csv|sim9_diag_*.csv|sim12_diag_*.csv|sim13_diag_*.csv  (리터럴)

이 레포는 그 형태로 이미 세 번 당했다(심 목록 3중 하드코딩 / 동기화 목록 stale /
월별 분할의 글롭 소유권).

여기서는 **심이 아니라 writer로 파일을 가른다**(`decisions_<날짜>_<runner>.csv`).
파일 수가 심 수(16개, 계속 는다)가 아니라 writer 수(2개, 안 는다)에 묶이므로
매니페스트도 제외 목록도 자리가 늘지 않는다. 기존 `sim_diag`는 심별 상세
진단이라는 다른 목적이므로 그대로 둔다.

## 왜 필요한가 — 그림자 운전의 판정 재료

폰 워커와 옛 경로(Actions)가 **같은 결정을 내리는가**를 5거래일 확인해야 주문을
넘긴다. 그런데 둘은 서로 다른 시각에 다른 시세를 본다 — 30초만 어긋나도
체결강도·현재가가 달라 결정이 갈린다. **문자 그대로의 "불일치 0"은 달성 불가능하다.**

그래서 `input_hash`를 함께 남긴다. 판정은 이렇게 바뀐다:

    input_hash가 같은 (cycle_id, sim, code)에서 decision이 다르면  → 진짜 불일치
    input_hash가 다르면                                          → 시세가 달랐다

이 열이 없으면 모든 차이가 "시세가 달랐나 보다"로 뭉개지고, 게이트가 아무것도
막지 못한다.
"""
import csv
import hashlib
import os

from src.core import clock

COLUMNS = ('cycle_id', 'ts', 'runner', 'sim', 'code', 'decision', 'reason',
           'input_hash')

# 결정에 실제로 쓰이는 입력만 해싱한다. **전체 키를 해싱하면 안 된다** —
# 무관한 필드 하나만 달라도 '입력이 달랐다'가 되어 게이트가 모든 불일치를
# 면제해 버린다. 여기 목록은 `_enrich_universe`가 채우는 것과 같은 축이다.
INPUT_FIELDS = (
    'price', 'change_rate', 'amount', 'tick_power',
    'per', 'pbr', 'w52_hgpr', 'w52_lwpr',
    'open_price', 'day_high', 'day_low', 'prev_close',
    'frgn_fake_ntby_qty', 'orgn_fake_ntby_qty',
)


def day_path(today: str | None = None, data_dir: str = 'data',
             runner: str | None = None) -> str:
    """오늘 결정 로그의 경로: `decisions_<날짜>_<runner>.csv`.

    **파일 이름에 writer를 넣는 이유 — 소유권이다.** 심은 두 워크플로에 나뉘어
    돈다(버즈 불필요 심은 trading.yml의 60초 루프, sim1 같은 버즈 심은
    scraper.yml). 파일이 하나면 둘이 같은 파일을 db-data에 밀어 **뒤에 끝난
    쪽이 앞의 것을 되돌린다**(lost update). 그 고장은 워크플로가 초록인 채로
    일어나 안 보인다 — `tests/test_workflow_file_ownership.py`가 막는 바로 그것.

    writer별로 가르면 각자 자기 파일만 쓰므로 충돌이 없고, 파일 수는 **writer
    수만큼**이지 심 수만큼이 아니다(심이 늘어도 자리가 늘지 않는다).
    비교는 `runner` 열로 한다 — 폰(phone) vs 돈 경로(actions-trading).

    하루 한 파일인 이유: 2분 격자가 매 사이클 통째로 db-data에 올리므로 월별로
    두면 파일이 계속 커진다(diag가 같은 이유로 일별이다).
    """
    stamp = today or clock.now().strftime('%Y%m%d')
    who = runner or runner_name()
    return os.path.join(data_dir, f'decisions_{stamp}_{who}.csv')


def input_hash(stock: dict) -> str:
    """이 종목의 **결정 입력** 지문. 12자 hex.

    없는 필드는 아무것도 기여하지 않고, 0인 필드는 `price=0`으로 기여한다 —
    **결손과 0은 다른 입력이다.** 이 레포가 반복해서 당한 혼동이라 해시에서도
    가른다.
    """
    parts = [f'{f}={stock[f]!r}' for f in INPUT_FIELDS if f in stock]
    raw = '|'.join(parts).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:12]


def build_rows(sim: str, candidates, funnel, orders, *, runner: str,
               cycle_id=None, ts: str | None = None) -> list[dict]:
    """이번 사이클 이 심의 결정 행들. **순수 함수** — I/O도 시계도 없다.

    한 후보의 결정은 셋 중 하나다:
      entry  이번에 샀다
      skip   탈락했다(이유가 있다)
      seen   들여다봤지만 기록이 없다 — 조기종료(max_holdings에서 break)로
             평가에 도달하지 못한 경우다. '설명 못 함'이 아니라 '평가 안 함'이라
             따로 표시한다. 이걸 skip에 섞으면 불일치 판정이 오염된다.
    """
    by_code = {}
    for c in candidates or []:
        code = (c or {}).get('code')
        if code:
            by_code.setdefault(code, c)

    reasons = {}
    for f in funnel or []:
        code = (f or {}).get('code')
        if code and code not in reasons:
            reasons[code] = (f or {}).get('reason', '')

    bought = [o.get('code') for o in (orders or [])
              if o.get('action') == 'BUY' and o.get('code')]

    rows = []
    seen_codes = []
    for code in bought:
        seen_codes.append(code)
        rows.append({'code': code, 'decision': 'entry', 'reason': 'entry'})
    for code, reason in reasons.items():
        if code in seen_codes:
            continue
        seen_codes.append(code)
        rows.append({'code': code, 'decision': 'skip', 'reason': reason})
    for code in by_code:
        if code not in seen_codes:
            rows.append({'code': code, 'decision': 'seen', 'reason': ''})

    for r in rows:
        r['cycle_id'] = '' if cycle_id is None else cycle_id
        r['ts'] = ts or ''
        r['runner'] = runner
        r['sim'] = sim
        r['input_hash'] = input_hash(by_code.get(r['code']) or {})
    return rows


def runner_name() -> str:
    """누가 이 결정을 냈나. 폰 워커는 `STOCKBOT_RUNNER=phone`으로 띄운다.

    기본값이 'actions'인 이유: 지금 도는 경로가 그것이고, 환경변수를 빠뜨린
    폰이 'actions'로 기록되면 **비교가 자기 자신과 이뤄져 불일치가 영원히 0**이
    된다. 그건 게이트가 통과하는 게 아니라 없어지는 것이다 — 3단계 셋업에서
    이 변수를 확인하는 것이 그래서 체크리스트에 들어간다.
    """
    return (os.environ.get('STOCKBOT_RUNNER') or 'actions').strip() or 'actions'


def append(rows: list, path: str | None = None, log=print) -> int:
    """행들을 추가한다. 추가된 수 반환.

    기록 실패로 심이 죽으면 안 되므로 삼키되, **시끄럽게 삼킨다** —
    `sim_diag`가 자기 실패를 진단 못 해 db-data에 파일이 0개인 것을 오래
    못 찾았던 전례가 있다. 정상 경로는 조용하다(성공은 반환값으로 말한다).
    """
    if not rows:
        return 0
    try:
        path = path or day_path()
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if is_new:
                w.writeheader()
            for r in rows:
                w.writerow({c: r.get(c, '') for c in COLUMNS})
        return len(rows)
    except Exception as e:
        log(f'[decision_log] 기록 실패 — {type(e).__name__}: {e} (경로 {path})')
        return 0
