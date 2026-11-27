# -*- coding: utf-8 -*-
"""us_trading.yml이 db-data와 주고받는 파일 — US 심 등록부에서 **파생**한다.

us_trading.yml은 `git checkout db-data -- data/`로 **트리 전체**(2026-11-26 기준
713MB·2,471파일)를 실체화하고, 배포에서도 전체를 clone한다. 그런데 이 루프가
실제로 읽고 쓰는 건 심당 세 파일(감시목록·상태·매매기록)과 알림 쿨다운뿐이다 —
2026-11-27 기준 **13개 / 약 200KB**.

열거할 수 있으니 열거한다. 그러면 "배포 목록 ⊄ 복원 목록"이 구성적으로 불가능해진다
(2026-08-05 심9-1 고장이 그 유형이다 — 두 목록이 갈려 매매기록 8건이 2행만 남았다).
배포 스텝이 `cp` 여덟 줄에 파일명을 박아 둔 것도 같이 사라진다: US 심이 하나 늘면
그 여덟 줄을 고쳐야 했고, 안 고치면 **그 심의 상태만 조용히 안 올라간다**.

감시목록이 등록부에 없는 이유: 심 모듈의 `WATCHLIST_PATH` 상수다. 등록부 `id`가
모듈 이름과 같아서(`us_sim1_minervini` → `src.strategy.simulators.us_sim1_minervini`)
import해서 읽는다. 감시목록이 없는 심은 그 상수가 없고, 그러면 두 파일만 낸다.

**import가 실패하면 비0으로 끝낸다.** 조용히 건너뛰면 그 심의 상태 파일이 복원·배포
목록에서 같이 빠지고, 다음 런이 초기 자본으로 시작해 그 백지를 db-data에 올린다.

    python3 scripts/us_db_data_files.py            # 복원 목록 (13개)
    python3 scripts/us_db_data_files.py --deploy   # 배포 목록 (9개, 복원의 부분집합)
"""
import importlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

_DIR = 'data'


def paths(deploy: bool = False) -> list[str]:
    """레포 루트 기준 경로. `deploy=True`면 **이 워크플로가 쓰는 것만**.

    복원과 배포 목록이 다르다. 감시목록은 이 루프가 **읽기만** 한다 —
    쓰는 쪽은 하루 1회 `us_eod_watchlist.yml`(run_eod_sim_us.save_watchlist)이다.
    배포에 넣으면 30분마다 도는 이 런이 런 시작 시점의 사본을 되돌려, EOD 배치가
    방금 쓴 새 감시목록을 덮는다(lost update). 2026-09-17에 국내에서 실제로 터진
    모양이다(리셋을 2분 뒤 trading 배포가 되돌려 14개 심 중 10개가 되돌아갔다).

    그래서 배포 ⊆ 복원이고, 테스트가 그 포함을 지킨다.
    """
    from src import alerts
    from src.strategy.us_registry import get_us_sim_registry

    out = []
    for entry in get_us_sim_registry():
        out.append(f"{_DIR}/{entry['state_file']}")
        out.append(f"{_DIR}/{entry['csv_file']}")
        if not deploy:
            mod = importlib.import_module(
                f"src.strategy.simulators.{entry['id']}")
            wl = getattr(mod, 'WATCHLIST_PATH', None)
            if wl:
                out.append(f'{_DIR}/{os.path.basename(wl)}')
    # 알림 쿨다운. writer가 셋이라 배포는 덮어쓰지 않고 병합한다
    # (scripts/merge_alert_dedup.py) — 2026-09-01에 이게 왕복하지 않아 결손
    # 알림이 세션 내내 2분 간격으로 나갔다.
    out.append(f'{_DIR}/{alerts.STATE_FILENAME}')
    return list(dict.fromkeys(out))


def main() -> int:
    # 줄끝을 LF로 고정한다. 윈도우 파이썬은 stdout을 텍스트 모드로 열어 CRLF를
    # 내고, 그러면 워크플로의 `[ -f "data/x.json\r" ]`가 **전부 거짓**이 되어
    # 모든 파일이 "미생성"으로 흡수된다($( )가 마지막 줄의 CR만 벗기므로 목록의
    # 맨 끝 한 개만 살아난다 — 2026-11-27 리허설에서 정확히 그 모양을 봤다).
    # CI 러너는 리눅스뿐이라 운영에서는 안 생기지만, 그러면 **로컬에서 리허설이
    # 불가능**하다. 한 줄로 그걸 되찾는다.
    sys.stdout.reconfigure(newline='\n')
    print('\n'.join(paths(deploy='--deploy' in sys.argv[1:])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
