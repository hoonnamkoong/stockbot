# -*- coding: utf-8 -*-
"""이력 절단 전 가드 — db-data에 쓰는 워크플로가 도는 중이면 막는다.

절단은 orphan 커밋 하나로 브랜치를 force-push하는 작업이다. 트리(현재 파일들)는
그대로 두고 **이력만** 버린다. db-data 이력을 읽는 소비자는 없다:

    대시보드   raw.githubusercontent.com/.../db-data/data/...  (HEAD만)
    워크플로   git clone --depth 1                              (14곳)
    신선도감사 경로별 **최신** 커밋 1건만

왜 필요한가 (2026-09-04 실측): 레포 1.0GB 중 db-data HEAD 스냅샷은 138.6MB다.
나머지 86%가 이력이고, 6737커밋 중 절반이 최근 15일치다. 데이터 브랜치의 이력은
아무도 안 읽는데 public 레포의 용량 상한을 먹는다.

덤으로 [[security-posture-public-repo]]의 미해결 부채가 같이 정리된다 — db-data
과거 커밋에 노출됐던 토큰·포트폴리오가 이력과 함께 사라진다.

## 위험과 방어

force-push는 **그 사이 들어온 커밋을 지운다.** db-data에는 하루 100회 넘게
push가 들어오고 거기에 심 상태·매매 기록이 있다. 두 겹으로 막는다:

  1. 이 스크립트: db-data에 쓰는 워크플로가 하나라도 도는 중이면 거부
  2. 워크플로 셸: clone 시점의 원격 HEAD가 push 직전까지 그대로인지 확인

2번이 결정적이고 1번은 진단이다 — 왜 막혔는지 사람에게 보여준다.
"""
import argparse
import json
import os
import sys
import time
from urllib import error, parse, request

# db-data에 push하는 워크플로 이름(= 워크플로 파일의 `name:`).
# 새 워크플로가 db-data에 쓰기 시작하면 여기도 늘어야 한다 —
# tests/test_truncate_guard.py가 그 동기화를 검사한다.
DB_DATA_WRITERS = {
    'Trading (실전 매매)',
    'Stock Scraper Schedule',
    'Premarket Data Collection',
    'EOD Data Collection',
    'US Trading (미국 심 페이퍼 매매)',
    'US EOD Watchlist (미국 심 감시목록)',
    'Fast Token Refresh',
    'Monthly Data Archive (월간 아카이브)',
}


def busy_writers(runs: list, writers=None) -> list:
    """지금 돌고 있는 db-data writer 이름들. 비어 있으면 절단해도 된다.

    queued도 바쁜 것으로 센다 — 절단 도중에 깨어나면 같은 사고다.
    """
    names = DB_DATA_WRITERS if writers is None else writers
    return sorted({r.get('name') for r in runs
                   if r.get('name') in names
                   and r.get('status') in ('queued', 'in_progress')})


def _fetch_runs(log=print) -> list | None:
    tok = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
    repo = os.environ.get('GITHUB_REPOSITORY') or 'hoonnamkoong/stockbot'
    if not tok:
        log('[Truncate] 토큰 없음 — 진행 중 런을 확인할 수 없다')
        return None
    out = []
    for status in ('in_progress', 'queued'):
        url = (f'https://api.github.com/repos/{repo}/actions/runs'
               f'?status={status}&per_page=100')
        try:
            req = request.Request(url, headers={
                'Authorization': f'token {tok}',
                'Accept': 'application/vnd.github.v3+json'})
            with request.urlopen(req, timeout=20) as res:
                out += json.loads(res.read().decode()).get('workflow_runs', [])
        except (error.URLError, OSError, ValueError) as e:
            log(f'[Truncate] 런 조회 실패: {e}')
            return None
    return out


def main(argv=None) -> int:
    """0=진행 가능, 2=writer가 도는 중(고장 아님), 1=확인 불가(고장).

    2와 1을 나누는 이유: trading은 2분마다 런을 띄우므로 어느 한 순간을 찍으면
    거의 항상 뭔가 돌고 있다. 그건 사고가 아니라 "지금은 때가 아니다"이고,
    거기에 텔레그램을 보내면 도배가 된다. 반면 런 조회 자체가 실패하면 그건
    진짜 이상이고 사람이 봐야 한다.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument('--retries', type=int, default=1,
                    help='빈틈을 찾을 때까지 재확인할 횟수')
    ap.add_argument('--interval', type=int, default=20, help='재확인 간격(초)')
    a = ap.parse_args(argv)

    for attempt in range(1, max(1, a.retries) + 1):
        runs = _fetch_runs()
        if runs is None:
            # 확인이 안 되면 진행하지 않는다. 절단은 되돌릴 수 없다 —
            # 모르면 멈추는 쪽이 맞다(fail-closed).
            print('[Truncate] 진행 중 런을 확인할 수 없어 중단한다')
            return 1
        busy = busy_writers(runs)
        if not busy:
            print(f'[Truncate] db-data writer 없음 (확인한 런 {len(runs)}개) — 진행 가능')
            return 0
        print(f'[Truncate] ({attempt}/{a.retries}) db-data writer가 돌고 있다: '
              f'{", ".join(busy)}')
        if attempt < a.retries:
            time.sleep(a.interval)
    print('[Truncate] 빈틈을 못 찾았다 — 마감 후(장중 트리거가 멈춘 창)에 다시 실행할 것')
    return 2


if __name__ == '__main__':
    sys.exit(main())
