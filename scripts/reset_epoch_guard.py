# -*- coding: utf-8 -*-
"""배포 직전에 — 이 런이 도는 사이 대시보드 리셋이 들어왔으면 리셋된 심 파일을 올리지 않는다.

db-data writer(trading·scraper·eod_data)는 런 시작에 db-data를 받아 계산하고, 끝에서
새로 clone한 db-data 위에 자기 사본을 cp로 덮는다. 그 사이 리셋 커밋이 들어오면
런 시작 시점의 옛 상태가 리셋을 되돌린다(lost update).

2026-09-17 실제로 터졌다: 14:04 리셋(1c34cebcf)을 14:06 trading 배포(dd1810e52)가
덮어 14개 심 중 10개가 리셋 전 값으로 돌아갔다. 두 커밋 모두 정상이었고 대시보드
차트만 옛 성적을 보여줬다.

리셋 API(src/app/api/simulation/reset)는 같은 커밋에 `sim_reset_epoch.json`을 쓴다.
런 시작 때 받은 사본(로컬)과 방금 clone한 사본(원격)의 reset_id가 다르면, 원격
마커의 `files`에 적힌 파일을 로컬 data/에서 지운다 — 뒤따르는 cp 루프는 없는 파일을
건너뛴다. 그 심의 이번 사이클 결과는 버려지고, 다음 런이 리셋된 상태에서 시작한다.

목록을 매니페스트에서 다시 도출하지 않는 이유: 리셋이 실제로 쓴 파일이 정확히
보호 대상이고, 이 스크립트가 src 패키지(와 그 의존)를 import하지 않아도 된다.

사용: python3 scripts/reset_epoch_guard.py <clone한 data 디렉터리> [로컬 data 디렉터리]
마커가 깨져 있으면 0이 아닌 코드로 끝난다 — 모르고 올리면 리셋이 또 사라진다.
"""
import json
import os
import sys

MARKER = 'sim_reset_epoch.json'


def _read(path: str):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8-sig') as f:
        return json.load(f)


def guard(remote_dir: str, local_dir: str = 'data') -> list:
    """리셋이 끼어들었으면 로컬에서 지운 파일 목록을, 아니면 []를 돌려준다."""
    remote = _read(os.path.join(remote_dir, MARKER))
    local = _read(os.path.join(local_dir, MARKER))
    remote_id = remote.get('reset_id') if remote else None
    local_id = local.get('reset_id') if local else None
    if remote_id == local_id:
        return []

    dropped = []
    for name in remote.get('files', []):
        # 마커는 원격에서 온 값이다 — 경로 탈출을 막는다.
        if os.path.basename(name) != name:
            raise ValueError(f'마커의 파일명이 경로를 포함한다: {name!r}')
        p = os.path.join(local_dir, name)
        if os.path.exists(p):
            os.remove(p)
            dropped.append(name)
    return dropped


def main(argv: list) -> int:
    if len(argv) < 2:
        print('사용: reset_epoch_guard.py <remote data dir> [local data dir]')
        return 2
    dropped = guard(argv[1], argv[2] if len(argv) > 2 else 'data')
    if dropped:
        print(f'[리셋 가드] 런 도중 리셋이 들어왔다 — 리셋된 파일 {len(dropped)}개를 '
              f'이번 배포에서 뺀다: {", ".join(dropped)}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
