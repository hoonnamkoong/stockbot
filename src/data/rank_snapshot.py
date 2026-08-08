"""순위 차분 — 게시글 증분의 돈 버전.

2026-08-09 재구성의 핵심. 게시글 증분은 가격에 **후행**한다(직전 10분 수익률과
+0.082, 향후와는 −0.040). 행동경제학이 말하는 것은 "사람들이 글을 쓴다"가 아니라
"비합리적으로 사들인다"이고, 사는 행위는 KIS 순위에 먼저 나타난다.

**추가 API 호출이 0이다.** KIS 순위 API는 몇 종목을 가져오든 호출 1번이고
(`rows[:limit]`으로 자를 뿐), 지금 그 결과는 매 사이클 버려진다 —
`KISDataProvider._set_rank_cache`가 TTL 캐시라 직전 스냅샷이 남지 않는다.
저장하고 빼기만 하면 신호가 생긴다.

pandas를 쓰지 않는다. 이 모듈은 trading.yml(requirements-trade.txt) 경로에서
60초마다 돌고, 무거운 import 하나가 셋업 시간을 늘려 매매 주기의 하한이 된다
(tests/test_trade_loop_imports.py가 지킨다).
"""

import csv
import json
import os

# 직전 스냅샷에 없던 종목의 '이전 순위'. 숫자로 적으면 지어낸 값이 되고,
# 빈칸으로 두면 '조회 실패'와 구분되지 않는다.
RANK_ABSENT = 'absent'


def rank_map(rows) -> dict[str, int]:
    """순위 응답(이미 순위 순)을 {code: 1-based 순위}로.

    같은 종목이 두 번 오면 **더 좋은 순위**를 남긴다 — 여러 순위 API
    (등락률·거래량·외인기관)를 합치면 중복이 정상적으로 생긴다.

    코드가 없는 행은 순위 자리를 **소비하지 않는다.** 파싱 실패한 행이 스냅샷마다
    들쭉날쭉 나타나면 그 아래 종목들의 순위가 통째로 밀려, 실제로는 가만히 있던
    종목에 가짜 delta가 생긴다. 유효한 행들 사이의 상대 순서만 센다.
    """
    out: dict[str, int] = {}
    for r in rows or []:
        code = (r or {}).get('code')
        if not code or code in out:
            continue
        out[code] = len(out) + 1
    return out


def diff_ranks(prev: dict | None, curr: dict) -> dict[str, dict]:
    """직전 스냅샷 대비 순위 변화. 현재 순위에 있는 종목만 돌려준다.

    delta: 순위 상승폭(양수 = 올라옴). 5위→2위면 +3.
      **신규 진입은 None이다.** 순위 밖에 있던 종목의 상승폭은 모르는 값이고,
      0으로 적으면 '변화 없음'과 뭉개지며 큰 수로 적으면 지어낸 값이다.

    warmup: 직전 스냅샷 자체가 없는 첫 사이클. 이때는 전 종목이 신규로 잡히는데
      그걸 '급등'으로 읽으면 매일 첫 사이클에 전 종목이 트리거된다.

    순위에서 빠진 종목은 돌려주지 않는다 — 이번 사이클의 관측 대상이 아니고
    현재가도 없다.
    """
    warmup = prev is None
    base = prev or {}
    out: dict[str, dict] = {}
    for code, rank in (curr or {}).items():
        prev_rank = base.get(code)
        is_new = prev_rank is None
        out[code] = {
            'rank': rank,
            'prev_rank': RANK_ABSENT if is_new else prev_rank,
            'delta': None if is_new else prev_rank - rank,
            'is_new': is_new,
            'warmup': warmup,
        }
    return out


# 직전 스냅샷. **db-data를 왕복해야 한다** — 컨테이너가 매 런 새로 뜨므로
# 이 파일이 배포되지 않으면 모든 사이클이 warmup이 되고 delta가 영원히 비어
# 신호가 통째로 사라진다. (2026-08-08 국면 게이트에서 같은 함정을 겪었다)
STATE_FILENAME = 'rank_state.json'

COLUMNS = [
    'cycle_id',          # 조인 키. sim_diag·1분봉과 같은 120초 격자
    'ts', 'code', 'name',
    'rank', 'prev_rank', 'delta', 'is_new', 'warmup',
    # 순위 응답이 이미 주는 값들 — 추가 호출 0
    'price', 'change_rate', 'acml_vol', 'amount',
]


def month_path(now, data_dir: str = 'data') -> str:
    """월별 분할. sim_diag·post_archive와 같은 이유로 한 파일이 무한정 커지는 것을 막는다."""
    return os.path.join(data_dir, f"money_{now.strftime('%Y-%m')}.csv")


def load_state(data_dir: str = 'data') -> dict | None:
    """직전 스냅샷. 없거나 깨졌으면 **None**이다.

    빈 dict를 돌려주면 '직전에 아무 종목도 없었다'가 되어 전 종목이 신규로 잡히는데
    warmup 표시가 안 붙는다 — 그러면 첫 사이클의 전 종목이 급등 신호로 읽힌다.
    """
    try:
        with open(os.path.join(data_dir, STATE_FILENAME), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        ranks = raw.get('ranks')
        return {str(k): int(v) for k, v in ranks.items()} if isinstance(ranks, dict) else None
    except Exception:
        return None


def save_state(snapshot: dict, now, data_dir: str = 'data') -> None:
    path = os.path.join(data_dir, STATE_FILENAME)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'at': now.isoformat(), 'ranks': snapshot}, f, ensure_ascii=False)


def build_records(cycle_id, now, rows, diff: dict) -> list[dict]:
    """순위 응답 + 차분을 CSV 한 행씩으로. 순위에 있는 종목 전수를 남긴다.

    진입한 종목만 남기면 "왜 이건 걸렀나"를 영영 못 본다 — Sim1이 6개월간 실패
    원인을 몰랐던 이유가 그것이었다(sim_diag 독스트링).
    """
    out = []
    for r in rows or []:
        code = (r or {}).get('code')
        d = diff.get(code) if code else None
        if not d:
            continue
        out.append({
            'cycle_id': cycle_id,
            'ts': now.isoformat(timespec='seconds'),
            'code': code,
            'name': r.get('name', ''),
            'rank': d['rank'],
            'prev_rank': d['prev_rank'],
            'delta': '' if d['delta'] is None else d['delta'],
            'is_new': int(bool(d['is_new'])),
            'warmup': int(bool(d['warmup'])),
            'price': r.get('price', ''),
            'change_rate': r.get('change_rate', ''),
            'acml_vol': r.get('acml_vol', ''),
            'amount': r.get('amount', ''),
        })
    return out


def append_records(records: list[dict], path: str) -> int:
    """월별 CSV에 덧붙인다. 헤더는 파일이 없을 때만."""
    if not records:
        return 0
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    is_new_file = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        if is_new_file:
            w.writeheader()
        for rec in records:
            w.writerow(rec)
    return len(records)
