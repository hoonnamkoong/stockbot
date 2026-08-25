"""us_eod_watchlist.yml의 배포 스텝도 심마다 워치리스트 파일명을 정적으로 나열한다.

tests/test_us_trading_workflow_deploy.py가 상태·CSV에 대해 지키는 것과 같은 자리다.
그쪽만 검증하고 있어서, US Sim3를 추가할 때 워치리스트 배포 목록은 손으로 찾아
넣어야 했다(2026-08-25). 여기에도 매니페스트 파생 검증을 둬서 다음 심이 같은
함정에 빠지지 않게 한다 — 워치리스트가 db-data에 안 나가면 장중 루프가 읽을 파일이
없어 그 심은 조용히 매매를 한 건도 안 한다.

워치리스트 파일 경로는 매니페스트에 없고 각 심 모듈의 WATCHLIST_PATH가 정본이라,
등록된 심을 실제로 import해서 파일명을 얻는다.
"""
import importlib
import os

import yaml

from src.strategy.us_registry import MANIFEST_PATH

WF = os.path.join(os.path.dirname(__file__), '..', '.github', 'workflows',
                  'us_eod_watchlist.yml')


def _registered_watchlist_files():
    with open(MANIFEST_PATH, encoding='utf-8') as f:
        manifest = yaml.safe_load(f)
    out = {}
    for s in manifest.get('simulators', []):
        if not s.get('active', True):
            continue
        mod = importlib.import_module(s['module'])
        path = getattr(mod, 'WATCHLIST_PATH', None)
        if path:                      # 워치리스트를 안 쓰는 심은 검증 대상이 아니다
            out[s['id']] = os.path.basename(path)
    return out


def test_every_registered_sim_watchlist_is_deployed():
    files = _registered_watchlist_files()
    assert files, '워치리스트를 쓰는 US 심이 하나도 안 잡혔다 — 탐지 로직이 깨졌다'

    with open(WF, encoding='utf-8') as f:
        deploy = f.read().split('Deploy watchlist (db-data)', 1)[1]

    for sim_id, fname in files.items():
        assert fname in deploy, (
            f'{fname}({sim_id})이 us_eod_watchlist.yml 배포 스텝에 없다 — '
            f'장중 루프가 읽을 워치리스트가 db-data에 없어 이 심은 매매를 한 건도 안 한다')
