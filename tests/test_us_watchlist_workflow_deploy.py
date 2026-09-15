"""us_eod_watchlist.yml의 배포 스텝도 심마다 워치리스트 파일명을 정적으로 나열한다.

tests/test_us_trading_workflow_deploy.py가 상태·CSV에 대해 지키는 것과 같은 자리다.
그쪽만 검증하고 있어서, US Sim3를 추가할 때 워치리스트 배포 목록은 손으로 찾아
넣어야 했다(2026-08-25). 여기에도 매니페스트 파생 검증을 둬서 다음 심이 같은
함정에 빠지지 않게 한다 — 워치리스트가 db-data에 안 나가면 장중 루프가 읽을 파일이
없어 그 심은 조용히 매매를 한 건도 안 한다.

워치리스트 파일 경로는 매니페스트에 없고 각 심 모듈의 WATCHLIST_PATH가 정본이라,
등록된 심을 실제로 import해서 파일명을 얻는다.
"""
import fnmatch
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


# ── 소유권: scraper.yml이 되돌리지 않는가 (2026-09-01) ────────────────
# 배포되는 것만으로는 부족하다. 2026-09-01에 배치가 10:14 KST에 워치리스트를
# 20260901로 갱신했는데, scraper.yml의 `cp data/*.json`이 10:17 KST에 **런 시작
# 시점 사본**으로 20260831을 다시 올려 3분 만에 되돌렸다(커밋 48cb7f133 →
# 6678f04b3). load_watchlist는 날짜 불일치에 fail-closed라 US 심 3개가 그 세션
# 내내 후보 0이었고, 결손 알림이 2분마다 나갔다.
#
# 되돌림은 실패로 안 보인다 — 두 워크플로 모두 초록이고 파일만 하루 과거다.

def _scraper_skip_patterns() -> list[str]:
    path = os.path.join(os.path.dirname(WF), 'scraper.yml')
    with open(path, encoding='utf-8') as f:
        deploy = f.read().split('Deploy Data to db-data branch', 1)[1]
    return [p.strip() for line in deploy.splitlines() if 'continue' in line
            for p in line.strip().split(')', 1)[0].split('|')]


def test_scraper_does_not_deploy_the_us_watchlists():
    """writer는 us_eod_watchlist.yml 하나다."""
    patterns = _scraper_skip_patterns()
    for sim_id, fname in _registered_watchlist_files().items():
        assert any(fnmatch.fnmatch(fname, p) for p in patterns), (
            f'{fname}({sim_id})이 scraper.yml 배포 제외 목록에 없다 — 배치가 '
            f'갱신한 워치리스트를 런 시작 시점 사본으로 되돌린다.')


def test_scraper_does_not_deploy_the_us_universe():
    """유니버스도 같은 배치가 소유한다. 되돌리면 나스닥 스크리너가 막혔을 때의
    폴백이 옛 종목 목록으로 돌아간다."""
    assert any(fnmatch.fnmatch('us_universe.json', p)
               for p in _scraper_skip_patterns()), \
        'us_universe.json이 scraper.yml 배포 제외 목록에 없다'


# ── 보유 종목 청산 지표는 배치가 US Sim1 상태를 읽어야 실린다 (2026-09-15) ────
# US Sim1의 50일선 이탈 청산은 ma50을 그날 워치리스트에서 읽는데, 워치리스트
# 진입 자격(_trend_template_ok)에 `price > ma50`이 들어 있어 "50일선을 깬 종목"은
# 정의상 목록에 못 오른다. 배치가 보유 종목에 한해 ma50을 따로 실어 주려면
# 상태 파일(data/sim_us1minervini_state.json)이 러너에 있어야 하는데, 이 파일은
# main이 아니라 db-data에만 있다 — 복원 스텝이 없으면 코드만 고쳐도 무효다.

def test_workflow_restores_sim1_state_for_exit_metrics():
    with open(WF, encoding='utf-8') as f:
        text = f.read()
    restore = text.split('Restore previous universe (db-data)', 1)[1] \
                  .split('- name:', 1)[0]
    assert 'sim_us1minervini_state.json' in restore, (
        'us_eod_watchlist.yml이 US Sim1 상태를 db-data에서 복원하지 않는다 — '
        '보유 종목 ma50이 워치리스트에 안 실려 50일선 이탈 청산이 영영 발화하지 않는다')
