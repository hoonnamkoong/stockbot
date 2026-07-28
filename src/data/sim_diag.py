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


def month_path(sim: str, today: str = None) -> str:
    d = ''.join(ch for ch in str(today or _today()) if ch.isdigit())
    ym = f"{d[:4]}-{d[4:6]}" if len(d) >= 6 else 'unknown'
    return os.path.join(DATA_DIR, f"{sim}_diag_{ym}.csv")


def _today() -> str:
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y%m%d')


def _rotate_if_stale(path) -> str:
    """기존 파일 헤더가 현재 COLUMNS와 다르면 옆으로 치우고 새 파일을 쓰게 한다.

    append는 빈 파일일 때만 헤더를 쓴다. 컬럼이 늘어난 뒤 옛 파일에 이어 쓰면
    열이 조용히 어긋나 로그 전체가 못 쓰게 된다.
    """
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return path
    try:
        with open(path, encoding='utf-8') as f:
            head = f.readline().strip().lstrip('﻿').split(',')
    except Exception:
        return path
    if head == COLUMNS:
        return path
    base, ext = os.path.splitext(path)
    for i in range(1, 100):
        alt = f"{base}_v{i}{ext}"
        if not os.path.exists(alt):
            return alt
    return path


def append(sim: str, records: list, path: str = None) -> int:
    """진단 행들을 추가한다. 추가된 행 수 반환.

    로깅 실패로 심이 죽으면 안 되므로 모든 예외를 삼킨다.
    """
    if not records:
        return 0
    try:
        path = path or month_path(sim)
        path = _rotate_if_stale(path)
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
                w.writerow(row)
        return len(records)
    except Exception:
        return 0
