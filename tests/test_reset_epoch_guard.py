# -*- coding: utf-8 -*-
"""런 도중 대시보드 리셋이 들어오면 배포가 리셋을 되돌리지 않는가.

2026-09-17 14:04 리셋(1c34cebcf)을 14:06 trading 배포(dd1810e52)가 런 시작 시점
사본으로 덮어 14개 심 중 10개가 리셋 전 값으로 돌아갔다. 가드는 세 writer
(trading·scraper·eod_data) 모두의 배포 경로에 있어야 한다.
"""
import json
import os
import re

import pytest
import yaml

from scripts.reset_epoch_guard import MARKER, guard

WF_DIR = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows')


def _write(d, name, obj):
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(obj), encoding='utf-8')


def _setup(tmp_path, local_id, remote_id):
    local, remote = tmp_path / 'local', tmp_path / 'remote'
    files = ['sim_bull_state.json', 'trade_history_sim_bull.csv']
    for n in files + ['money_2026-09-17.csv']:
        _write(local, n, {})
    if local_id:
        _write(local, MARKER, {'reset_id': local_id, 'files': files})
    if remote_id:
        _write(remote, MARKER, {'reset_id': remote_id, 'files': files})
    else:
        remote.mkdir(parents=True, exist_ok=True)
    return local, remote


def test_런_도중_리셋이면_리셋된_파일만_뺀다(tmp_path):
    local, remote = _setup(tmp_path, 'A', 'B')
    dropped = guard(str(remote), str(local))
    assert sorted(dropped) == ['sim_bull_state.json', 'trade_history_sim_bull.csv']
    assert not (local / 'sim_bull_state.json').exists()
    # 리셋 대상이 아닌 산출물은 그대로 올라가야 한다.
    assert (local / 'money_2026-09-17.csv').exists()


def test_첫_리셋도_잡는다(tmp_path):
    """마커가 생기기 전에 시작한 런 — 로컬에는 마커가 없다."""
    local, remote = _setup(tmp_path, None, 'B')
    assert guard(str(remote), str(local))


@pytest.mark.parametrize('ids', [('A', 'A'), (None, None)])
def test_리셋이_없었으면_아무것도_안_뺀다(tmp_path, ids):
    local, remote = _setup(tmp_path, *ids)
    assert guard(str(remote), str(local)) == []
    assert (local / 'sim_bull_state.json').exists()


def test_경로가_든_파일명은_거부한다(tmp_path):
    local, remote = _setup(tmp_path, 'A', 'B')
    _write(remote, MARKER, {'reset_id': 'B', 'files': ['../x.json']})
    with pytest.raises(ValueError):
        guard(str(remote), str(local))


def _source(name):
    with open(os.path.join(WF_DIR, name), encoding='utf-8') as f:
        return '\n'.join(l for l in f.read().splitlines()
                         if not l.strip().startswith('#'))


@pytest.mark.parametrize('wf, clone_dir', [
    ('trading.yml', 'db_data_repo/data'),
    ('scraper.yml', 'db_data_repo/data'),
    ('eod_data.yml', 'db_repo/data'),
])
def test_KR_심_writer가_모두_cp_전에_가드를_부른다(wf, clone_dir):
    src = _source(wf)
    call = f'scripts/reset_epoch_guard.py {clone_dir}'
    assert call in src, f'{wf}: 배포 경로에 리셋 가드가 없다'
    # clone 뒤, 심 파일 cp 앞이어야 한다.
    at = src.index(call)
    clone = src.rfind('git clone', 0, at)
    assert clone != -1, f'{wf}: 가드가 clone보다 앞에 있다'
    assert re.search(r'cp .*(sim_|\$name|\$f)', src[at:]), f'{wf}: 가드 뒤에 cp가 없다'


def test_eod는_런_시작_마커를_받아둔다():
    """eod_data는 data/ 전체가 아니라 파일을 골라 받는다 — 마커도 받아야 비교가 된다."""
    assert f'state_repo/data/{MARKER}' in _source('eod_data.yml')


def test_scraper는_마커를_올리지_않는다():
    """마커의 writer는 리셋 API뿐이다. 옛 사본을 올리면 다음 런의 비교 기준이 틀어진다."""
    assert MARKER in _source('scraper.yml')
