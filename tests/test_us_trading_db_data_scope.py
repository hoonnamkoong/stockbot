# -*- coding: utf-8 -*-
"""us_trading.yml이 db-data에서 주고받는 범위.

이 루프가 실제로 쓰는 건 심당 세 파일(감시목록·상태·매매기록)과 알림 쿨다운뿐이다
— 2026-11-27 기준 **13개 / 약 123KB**. 그런데 `git checkout db-data -- data/`가
트리 전체를 실체화하고(실측 42초 / 130MB, 작업 트리로 713MB·2,471파일) 배포도
전체를 clone했다.

열거할 수 있으니 등록부에서 파생시킨다. 지키는 불변식이 셋이다.

1. **배포 ⊆ 복원.** 올릴 것을 받아 두지 않으면 append 파일이 잘린다
   (2026-08-05 심9-1 매매기록 8건 → 2행).
2. **감시목록은 복원에만 있다.** 쓰는 쪽은 하루 1회 `us_eod_watchlist.yml`이고,
   30분마다 도는 이 런이 올리면 EOD 배치가 방금 쓴 목록을 런 시작 시점 사본으로
   되돌린다(2026-09-17 국내에서 실제로 터진 모양 — 리셋을 2분 뒤 trading 배포가
   되돌려 14개 심 중 10개가 되돌아갔다).
3. **복원 실패는 멈춘다.** 예전 `|| true`는 fail-open이었다. 받기에 실패하면
   `base_simulator`가 `if os.path.exists(self.state_file)`이라 **네 심 전부 초기
   자본으로 리셋**되고, 그 백지가 배포 스텝에 실려 db-data의 진짜 이력을 덮는다.
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts import us_db_data_files as gen  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
WF = os.path.join(ROOT, '.github', 'workflows', 'us_trading.yml')


def _steps() -> dict:
    with open(WF, encoding='utf-8') as f:
        doc = yaml.safe_load(f)
    out = {}
    for job in doc['jobs'].values():
        for step in job.get('steps') or []:
            if step.get('run'):
                out[step.get('name')] = step['run']
    return out


def _code_only(body: str) -> str:
    return '\n'.join(ln for ln in body.split('\n')
                     if not ln.lstrip().startswith('#'))


def test_배포_목록은_복원_목록의_부분집합이다():
    restore = set(gen.paths())
    deploy = set(gen.paths(deploy=True))
    extra = deploy - restore
    assert not extra, f'올리는데 받지 않는 파일: {extra}'


def test_등록된_US_심_전원의_상태와_매매기록이_양쪽에_있다():
    """심이 하나 늘면 자동으로 따라와야 한다. 예전 배포 스텝은 `cp` 여덟 줄에
    파일명을 박아 둬서, 안 고치면 그 심의 상태만 조용히 안 올라갔다."""
    from src.strategy.us_registry import get_us_sim_registry
    restore, deploy = set(gen.paths()), set(gen.paths(deploy=True))
    reg = get_us_sim_registry()
    assert reg, '등록부가 비면 이 테스트는 아무것도 지키지 않는다'
    for entry in reg:
        for key in ('state_file', 'csv_file'):
            p = f"data/{entry[key]}"
            assert p in restore, f'{entry["id"]}의 {key}가 복원 목록에 없다'
            assert p in deploy, f'{entry["id"]}의 {key}가 배포 목록에 없다'


def test_감시목록은_복원에만_있고_배포에는_없다():
    restore, deploy = gen.paths(), gen.paths(deploy=True)
    wl = [p for p in restore if 'watchlist' in p]
    assert wl, '감시목록이 복원 목록에 없다 — 심이 유니버스를 못 읽는다'
    for p in wl:
        assert p not in deploy, (
            f'{p}를 올리면 EOD 배치가 방금 쓴 목록을 되돌린다(lost update)')


def test_심_모듈_import_실패는_조용히_넘어가지_않는다(monkeypatch):
    """조용히 건너뛰면 그 심의 상태가 복원·배포 목록에서 같이 빠지고, 다음 런이
    초기 자본으로 시작해 그 백지를 db-data에 올린다."""
    import src.strategy.us_registry as reg
    monkeypatch.setattr(
        reg, 'get_us_sim_registry',
        lambda *a, **kw: [{'id': 'us_sim_does_not_exist',
                           'state_file': 'x.json', 'csv_file': 'x.csv'}])
    try:
        gen.paths()
    except ModuleNotFoundError:
        return
    raise AssertionError('없는 심 모듈을 조용히 건너뛰었다')


def test_복원_스텝이_실패하면_멈춘다():
    body = _code_only(_steps()['Fetch remote state (db-data)'])
    assert 'fetch_db_data_files.sh' in body, '부분 클론 헬퍼를 쓰지 않는다'
    assert 'exit 1' in body, '복원 실패에 멈추는 경로가 없다'
    assert '|| true' not in body, (
        'fail-open이 남아 있다 — 받기 실패가 전 심 초기화로 번진다')
    assert 'git checkout db-data -- data/' not in body, (
        '트리 전체 체크아웃이 남아 있다(42초 / 130MB)')


def test_배포_스텝이_파생_목록과_부분_클론을_쓴다():
    body = _code_only(_steps()['Deploy state (db-data)'])
    assert 'us_db_data_files.py --deploy' in body, '배포 목록을 파생하지 않는다'
    clone = [ln for ln in body.split('\n') if 'git clone' in ln]
    assert len(clone) == 1, f'clone 줄이 {len(clone)}개'
    for flag in ('--filter=blob:none', '--sparse', '--depth 1'):
        assert flag in clone[0], f'clone 줄에 {flag}가 없다: {clone[0].strip()}'
    assert re.search(r'for\s+i\s+in\s+1\s+2\s+3', body), 'push 재시도가 없다'
    # 파일명을 박은 cp 여덟 줄이 돌아오면 안 된다.
    assert 'cp data/sim_us1minervini_state.json' not in body


def test_배포_재시도가_unshallow로_되돌아가지_않는다():
    """`git fetch --unshallow`는 부분 클론을 되돌려 130MB를 다시 받는다 —
    재시도 한 번에 이 PR의 절감이 사라진다. 그리고 db-data 6,707커밋에서
    rebase 경로는 실측 142초다(2026-08-26)."""
    body = _code_only(_steps()['Deploy state (db-data)'])
    for banned in ('--unshallow', 'pull --rebase'):
        assert banned not in body, f'{banned}가 남아 있다'
