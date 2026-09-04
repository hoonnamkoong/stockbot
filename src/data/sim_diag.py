"""시뮬레이터 진입 판단 진단 로그.

Sim1은 6개월간 왜 실패하는지 몰랐다. 백테스트에 69거래·승률 36.4%가 찍혔지만
어느 조건이 잘못 통과시켰는지 알 방법이 없었다 — 진입 시점의 지표를 아무도
남기지 않았기 때문이다. 실제 원인(`or buzz_count>=500`이 평상시 대형주만
통과시킴)은 진입 로그를 눈으로 뒤져서야 나왔다.

그래서 **진입한 종목만이 아니라 후보 전부**를 남긴다. 통과한 것만 보면
"왜 이건 걸렀나"를 영영 못 본다.

CSV·월별 분할 이유는 post_archive와 같다(배포 루프가 data/*.csv만 실어 나르고,
한 파일이 무한정 커지는 것을 막는다).
"""

import csv
import os
from datetime import datetime, timedelta, timezone

DATA_DIR = 'data'

COLUMNS = [
    'cycle_id',          # 조인 키. PipelineContext.cycle_id (120초 격자)
    'ts', 'sim', 'code', 'name',
    'decision',          # entry | skip
    'reason',            # skip 사유 (첫 번째로 걸린 게이트)
    # ── 진입 판단에 쓴 값들 ─────────────────────────────
    'price', 'change_rate', 'amount', 'adx', 'tick_power',
    'posts', 'unique_posters', 'posts_per_poster', 'avg_posts', 'buzz_ratio',
    'total_likes', 'likes_per_post', 'sov', 'z_posters', 'z_sov', 'z_likes',
    'ignition', 'hype_score', 'fact_score',
    # ── 이력 파생 (진입에는 아직 쓰지 않는다. Phase 2 입력) ──
    'z_hype', 'd_sov', 'd_hype', 'accel', 'accel_d1',
    'hist_missing', 'hist_days_ago', 'ignition4',
]


# 이번 사이클의 격자 번호. 파이프라인 진입점이 사이클 시작에 한 번 세팅한다.
#
# 왜 인자가 아니라 모듈 상태인가: 시뮬레이터는 ctx를 들고 있지 않다(생성자가
# initial_cash만 받는다). 전 심의 생성자에 cycle_id를 흘리면 변경이 넓어지는데,
# "지금이 몇 번째 사이클인가"는 본질적으로 주변 컨텍스트지 심의 속성이 아니다.
#
# 세팅 안 된 채로 쓰면 값이 빈칸으로 남는다. 여기서 시계를 다시 읽어 추정하지
# 않는 이유: 그러면 런이 격자 경계를 넘을 때 같은 사이클의 행들이 서로 다른
# 번호를 받아 조인이 조용히 깨진다. 빈칸은 "안 붙었다"가 눈에 보이지만,
# 어긋난 번호는 안 보인다.
_cycle_id = None


def set_cycle(cycle_id) -> None:
    """이번 사이클의 격자 번호를 정한다(PipelineContext.cycle_id)."""
    global _cycle_id
    _cycle_id = cycle_id


def day_path(sim: str, today: str = None) -> str:
    """**오늘** 진단 로그의 쓰기 경로.

    월별이던 시절, 이 파일들은 장중 2분 루프가 매 사이클 통째로 db-data에
    재커밋했다 — 2026-09-04 실측 sim12_diag_2026-09.csv가 3.7MB에 하루 100회다.
    일별로 쪼개면 지난 날짜 파일은 다시 쓰이지 않는다(rank_snapshot.day_path와
    같은 이유).

    ⚠ 읽을 때는 이 경로 하나만 열면 안 된다. COLUMNS가 바뀐 날은
    `_move_stale_if_needed`가 옛 파일을 `..._v1.csv`로 비켜놓고 정규 경로를 새로
    시작하므로, 그날 기록이 두 파일로 나뉜다 — `day_files()`/`month_files()`를 쓸 것.
    """
    d = ''.join(ch for ch in str(today or _today()) if ch.isdigit())
    ymd = f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) >= 8 else 'unknown'
    return os.path.join(DATA_DIR, f"{sim}_diag_{ymd}.csv")


def day_files(sim: str, today: str = None) -> list:
    """그날 진단 로그의 **모든** 파일 (정규 경로 + 컬럼 변경으로 갈라진 _vN).

    오래된 것부터 반환한다. 분석은 이걸 써야 한다 — day_path() 하나만 읽으면
    컬럼이 바뀐 날의 앞부분을 못 본다(2026-08에 cycle_id가 추가되며 실제로
    sim1_diag가 갈라졌다).
    """
    import glob
    base, ext = os.path.splitext(day_path(sim, today))
    # _v1, _v2 … 가 시간순으로 앞선다(옛 파일이 먼저 비켜났다).
    versioned = sorted(glob.glob(f"{base}_v*{ext}"))
    return versioned + ([base + ext] if os.path.exists(base + ext) else [])


def month_files(sim: str, today: str = None) -> list:
    """그 **달** 진단 로그의 모든 파일. 일별 분할 뒤에도 달 단위 분석이 필요하다.

    월별 파일(`sim1_diag_2026-08.csv`)과 일별 파일(`sim1_diag_2026-08-10.csv`)이
    함께 잡힌다 — 2026-09-04 전환 이전 데이터가 월별로 남아 있기 때문이다.
    파일명을 짚지 말고 이 함수를 쓸 것([[monthly-split-needs-glob-ownership]]).
    """
    import glob
    d = ''.join(ch for ch in str(today or _today()) if ch.isdigit())
    ym = f"{d[:4]}-{d[4:6]}" if len(d) >= 6 else 'unknown'
    pat = os.path.join(DATA_DIR, f"{sim}_diag_{ym}*.csv")
    return sorted(glob.glob(pat))


def _today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')


def _move_stale_if_needed(path) -> bool:
    """기존 파일 헤더가 현재 COLUMNS와 다르면 옆으로 옮긴다.

    성공하면 True를 반환한다. 실패하면 False를 반환하며, 이 경우 정규 경로를
    건드리지 않아 "열이 조용히 어긋나는" 사고를 방지한다.

    append는 빈 파일일 때만 헤더를 쓴다. 컬럼이 늘어난 뒤 옛 파일에 이어 쓰면
    열이 조용히 어긋나 로그 전체가 못 쓰게 된다.

    이 함수는 **한 번만** 옛 파일을 옆으로 옮기고, 정규 경로는 비워둔다.
    다음 호출에서는 정규 경로의 헤더가 이미 일치하므로 다시 이동이 일어나지 않는다.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return True
    try:
        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().lstrip('﻿').split(',')
    except Exception:
        return True
    if head == COLUMNS:
        return True
    # 옛 헤더를 가진 파일을 옆으로 옮긴다
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        alt = f"{base}_v{i}{ext}"
        if not os.path.exists(alt):
            try:
                os.rename(path, alt)
                return True
            except Exception:
                # 파일 잠김 등으로 옮기 실패 — 정규 경로를 건드리지 않음
                return False
    # range 소진 시 — 이동 불가
    return False


def _say(log, msg: str) -> None:
    """로거가 터져도 심을 죽이지 않는다."""
    try:
        log(msg)
    except Exception:
        pass


def append(sim: str, records: list, path: str = None, log=print) -> int:
    """진단 행들을 추가한다. 추가된 행 수 반환.

    로깅 실패로 심이 죽으면 안 되므로 모든 예외를 삼킨다. **다만 시끄럽게
    삼킨다** — 0을 돌려주는 길이 셋인데(records 비었음 / 옛 헤더 파일을 못
    비켜놓음 / 예외) 예전에는 전부 같은 `return 0`이라 로그에서 구분되지 않았다.

    2026-08-09에 db-data의 diag 파일이 0개인 것이 드러났는데, 원인을 특정할 수
    없었던 이유가 정확히 이것이다. "진단을 남기는 장치"가 자기 실패를 진단하지
    못하면 그 장치는 없는 것과 같다.

    정상 경로는 조용하다 — 사이클마다 성공 로그를 찍으면 그게 소음이 되어
    실패 줄을 덮는다. 성공은 반환값으로 말한다(호출부가 그걸 로그에 남긴다).
    """
    if not records:
        _say(log, f'[diag] {sim}: 기록할 행이 없습니다(records 비어 있음) — '
                  f'후보가 0개였거나 판단 루프에 도달하지 못했습니다')
        return 0
    try:
        path = path or day_path(sim)
        if not _move_stale_if_needed(path):
            # 옛 파일을 비켜놓지 못했으면 로그를 쓰지 않아 데이터 정합성 유지.
            # 판단 자체는 옳다(열이 어긋나느니 안 쓰는 게 낫다) — 침묵만 고친다.
            _say(log, f'[diag] {sim}: 옛 헤더 파일을 비켜놓지 못해 이번 기록을 '
                      f'생략합니다 — {path}')
            return 0
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        ts = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
        is_new = not os.path.exists(path) or os.path.getsize(path) == 0
        with open(path, 'a', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS)
            if is_new:
                w.writeheader()
            for r in records:
                row = {c: r.get(c, '') for c in COLUMNS}
                row['ts'] = row['ts'] or ts
                row['sim'] = sim
                # 한 사이클의 모든 행은 같은 번호를 받아야 한다 — 심끼리, 그리고
                # 나중에 t+N 행과 조인하는 근거가 이것뿐이다.
                if row['cycle_id'] == '' and _cycle_id is not None:
                    row['cycle_id'] = _cycle_id
                w.writerow(row)
        return len(records)
    except Exception as e:
        _say(log, f'[diag] {sim}: 기록 실패 — {type(e).__name__}: {e} (경로 {path})')
        return 0
