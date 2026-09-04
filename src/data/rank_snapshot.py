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
    """**한 블록의** 순위 응답(이미 순위 순)을 {code: 1-based 순위}로.

    블록을 이어붙여 넘기지 말 것. 순위 공간은 블록마다 따로다(snapshot 참고).

    코드가 없거나 이미 나온 행은 순위 자리를 **소비하지 않는다.** 파싱 실패한 행이
    스냅샷마다 들쭉날쭉 나타나면 그 아래 종목들의 순위가 통째로 밀려, 실제로는
    가만히 있던 종목에 가짜 delta가 생긴다. 유효한 행들 사이의 상대 순서만 센다.
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
    'ts',
    'source',            # 어느 순위인가. (cycle_id, source, code)가 유일 키다
    'code', 'name',
    'rank', 'prev_rank', 'delta', 'is_new', 'warmup',
    # 순위 응답이 이미 주는 값들 — 추가 호출 0
    'price', 'change_rate', 'acml_vol', 'amount',
]


def day_path(now, data_dir: str = 'data') -> str:
    """**일별** 분할.

    월별이던 시절, 이 파일은 하루 100번 통째로 db-data에 재커밋됐다(장중 2분 루프가
    매 사이클 배포한다 — 건너뛰면 러너가 다음 런에서 원격본을 복원하므로 그 사이클
    행이 유실된다). 월말이면 24MB짜리를 100번 밀게 되고, 2026-09-04 실측에서
    db-data 6737커밋·레포 1.0GB의 86%가 그렇게 쌓인 이력이었다.

    일별로 쪼개면 하루치가 1MB 수준이고, **지난 날짜 파일은 다시 쓰이지 않는다.**
    읽는 쪽은 파일명을 짚지 말고 `money_*.csv` 글롭 + 날짜 필터를 쓸 것
    (scripts/save_minute_bars.py) — 월↔일 전환일에는 두 형식이 함께 있다.
    """
    return os.path.join(data_dir, f"money_{now.strftime('%Y-%m-%d')}.csv")


def load_state(data_dir: str = 'data') -> dict | None:
    """직전 스냅샷 {source: {code: rank}}. 없거나 깨졌으면 **None**이다.

    빈 dict를 돌려주면 '직전에 아무 종목도 없었다'가 되어 전 종목이 신규로 잡히는데
    warmup 표시가 안 붙는다 — 그러면 첫 사이클의 전 종목이 급등 신호로 읽힌다.

    구 포맷({code: rank} 평면)은 통째로 버린다. 그대로 읽으면 source 자리에
    종목코드가 앉아, 뜻이 다른 숫자끼리 빼게 된다. 한 사이클 warmup이 낫다.
    """
    try:
        with open(os.path.join(data_dir, STATE_FILENAME), 'r', encoding='utf-8') as f:
            raw = json.load(f)
        ranks = raw.get('ranks')
        if not isinstance(ranks, dict) or not ranks:
            return None
        out = {}
        for source, m in ranks.items():
            if not isinstance(m, dict):
                return None
            out[str(source)] = {str(k): int(v) for k, v in m.items()}
        return out
    except Exception:
        return None


def save_state(state: dict, now, data_dir: str = 'data') -> None:
    """{source: {code: rank}}를 통째로 덮어쓴다."""
    path = os.path.join(data_dir, STATE_FILENAME)
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'at': now.isoformat(), 'ranks': state}, f, ensure_ascii=False)


def build_records(cycle_id, now, source: str, rows, diff: dict) -> list[dict]:
    """한 블록의 순위 응답 + 차분을 CSV 한 행씩으로. 순위에 있는 종목 전수를 남긴다.

    진입한 종목만 남기면 "왜 이건 걸렀나"를 영영 못 본다 — Sim1이 6개월간 실패
    원인을 몰랐던 이유가 그것이었다(sim_diag 독스트링).

    같은 코드가 블록 안에 두 번 오면 한 행만 남긴다. 두 행을 적으면
    (cycle_id, source, code) 조인이 1:N이 된다.
    """
    out = []
    seen = set()
    for r in rows or []:
        code = (r or {}).get('code')
        d = diff.get(code) if code else None
        if not d or code in seen:
            continue
        seen.add(code)
        out.append({
            'cycle_id': cycle_id,
            'ts': now.isoformat(timespec='seconds'),
            'source': source,
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


def snapshot(blocks, prev: dict | None, cycle_id, now) -> tuple[dict, list[dict]]:
    """블록들을 각자의 순위 공간에서 차분한다. → (새 상태, CSV 행들)

    blocks: [(source, rows)] — 예: [('kospi_updown', rows), ('frgn_inst', rows)]

    **블록을 이어붙여 하나의 1..N을 매기지 않는다.** 그렇게 하던 시절에는
    중복 코드가 순위 자리를 소비하지 않아, 사이클마다 달라지는 교집합 크기만큼
    뒤 블록이 통째로 밀렸다 — 가만히 있던 수백 종목에 가짜 delta가 찍혔고,
    외인기관 순위의 market 기본값이 '0001'(코스피)이라 겹침은 상시였다.
    이어붙인 순위는 뜻도 없다: delta가 '순위가 올랐다'인지 '블록이 바뀌었다'인지
    구분되지 않는다.

    처음 보는 source는 그 블록만 warmup이다(prev에 그 키가 없으면 None이 되고,
    diff_ranks가 warmup으로 표시한다). 블록을 추가한 첫 사이클에 그 블록 전체가
    급등으로 읽히지 않는다.

    **빈 직전 블록도 None으로 본다.** KIS가 응답 shape를 바꿔 전 행에서 code를
    못 뽑으면 rank_map이 {}가 되고 그게 저장된다(fetch는 성공했으니 결손 검사에
    안 걸린다). 그 {}를 '직전에 아무것도 없었다'로 읽으면 다음 사이클에 200종목이
    warmup 표시 없이 전부 신규 진입으로 잡힌다 — load_state가 빈 상태를 None으로
    돌려주는 것과 같은 이유다.
    """
    state: dict[str, dict] = {}
    records: list[dict] = []
    for source, rows in blocks:
        curr = rank_map(rows)
        diff = diff_ranks((prev or {}).get(source) or None, curr)
        state[source] = curr
        records += build_records(cycle_id, now, source, rows, diff)
    return state, records


def append_records(records: list[dict], path: str) -> int:
    """월별 CSV에 덧붙인다. 헤더는 파일이 없을 때만.

    헤더가 지금 스키마와 다르면 그 파일을 `.legacy`로 밀어내고 새로 시작한다.
    스키마가 바뀌면 옛 행은 뜻이 다르고, 폭이 다른 행을 한 헤더 아래 이어 붙이면
    파일이 조용히 어긋난 채 자란다. 지우지는 않는다 — 옆으로 치울 뿐이다.
    """
    if not records:
        return 0
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                header = (f.readline() or '').strip().split(',')
        except Exception:
            header = []
        if header != COLUMNS:
            os.replace(path, path + '.legacy')
    is_new_file = not os.path.exists(path)
    with open(path, 'a', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction='ignore')
        if is_new_file:
            w.writeheader()
        for rec in records:
            w.writerow(rec)
    return len(records)
