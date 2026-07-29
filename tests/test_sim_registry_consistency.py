"""심 목록이 4곳에 복제돼 있다 — 어긋나면 심이 조용히 사라진다.

2026-07-29 실제로 어긋나 있었다: 07-28에 추가한 심8·심9·심9-1이 리셋 목록과
일일 브리프에 등록되지 않아, 대시보드에서 '시뮬레이터 초기화'를 눌러도 셋은
옛 상태로 남고 15:00 브리프에도 나오지 않았다. 게다가 sim-reset-targets.test.ts가
`length === 9`로 그 누락을 고정하고 있었다.

진짜 해법은 매니페스트를 유일한 원천으로 삼는 것이고 그건 별도 설계 과제다.
그때까지 이 테스트가 드리프트를 막는다 — 새 심을 붙일 때 네 곳 중 하나라도
빠뜨리면 여기서 걸린다.

상태 파일명은 BaseSimulator가 `sim_{name.lower()}_state.json`으로 만든다.
그 name은 각 심의 super().__init__("Name") 인자라 소스에서 읽는다. 클래스를
인스턴스화하면 운영 상태 파일을 건드리므로 텍스트로만 읽는다.
"""
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

ROOT = os.path.join(os.path.dirname(__file__), '..')
MANIFEST = os.path.join(ROOT, 'src', 'strategy', 'strategy_manifest.yaml')
RESET_TS = os.path.join(ROOT, 'src', 'lib', 'sim-reset-targets.ts')
BRIEF_PY = os.path.join(ROOT, 'src', 'pipeline', 'daily_brief.py')
STATS_TS = os.path.join(ROOT, 'src', 'app', 'api', 'simulation', 'stats', 'route.ts')


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _active_sims():
    """활성 심 → {id: (상태파일명, 분석기여부)}."""
    manifest = yaml.safe_load(_read(MANIFEST))
    out = {}
    for s in manifest['simulators']:
        if not s.get('active', True):
            continue
        src = _read(os.path.join(ROOT, *s['module'].split('.')) + '.py')
        m = re.search(r'super\(\)\.__init__\(\s*"([^"]+)"', src)
        assert m, f"{s['id']}: super().__init__(\"Name\") 을 찾지 못했다"
        out[s['id']] = (f'sim_{m.group(1).lower()}_state.json',
                        'IS_ANALYZER = True' in src)
    return out


def _trading_sims():
    """매매하는 활성 심 → {id: 상태파일명}. 분석기(리베로)는 매매하지 않아 제외."""
    return {k: v[0] for k, v in _active_sims().items() if not v[1]}


def _state_files(text):
    return set(re.findall(r'(sim_[a-z0-9]+_state\.json)', text))


EXPECTED = _trading_sims()


def test_manifest_has_trading_sims():
    """전제 확인 — 매매심이 실제로 잡히는가(0개면 아래 대조가 무의미해진다)."""
    assert len(EXPECTED) >= 10, EXPECTED


def test_reset_targets_cover_every_trading_sim():
    """빠지면 대시보드 '시뮬레이터 초기화'가 그 심을 건너뛴다."""
    missing = set(EXPECTED.values()) - _state_files(_read(RESET_TS))
    assert not missing, f'sim-reset-targets.ts에 누락: {sorted(missing)}'


def test_daily_brief_derives_from_manifest():
    """브리프는 자체 목록을 갖지 않는다 — 매니페스트에서 파생한다."""
    from src.pipeline.daily_brief import SIM_BRIEF_TARGETS
    assert {t[1] for t in SIM_BRIEF_TARGETS} == set(EXPECTED.values())
    assert 'sim_libero_state.json' not in {t[1] for t in SIM_BRIEF_TARGETS}


def test_brief_is_ordered_for_humans_not_execution():
    """표시 순서는 실행 순서와 분리돼 있다.

    매니페스트 나열 순서는 실행 순서(국면 생산자가 소비자보다 앞)라 사람이
    읽기엔 뒤죽박죽이다(1,2,3,4,5,6,4-1,7,10,8,9,9-1). display_order가 그걸
    번호순으로 되돌린다.
    """
    from src.pipeline.daily_brief import SIM_BRIEF_TARGETS
    labels = [t[0] for t in SIM_BRIEF_TARGETS]
    assert labels.index('상승 단타형 (Sim 4-1)') == labels.index('상승 모멘텀형 (Sim 4)') + 1
    assert labels[-1] == '오케스트레이터 (Sim 10)'


def test_manifest_state_file_matches_class_naming_rule():
    """매니페스트에 적은 state_file이 BaseSimulator가 실제로 쓰는 경로와 같은가.

    손으로 적는 값이라 오타 한 글자로 없는 파일을 읽게 된다 — 그 경우 심의
    성과가 조용히 '측정 불가'로 나온다.
    """
    manifest = yaml.safe_load(_read(MANIFEST))
    declared = {s['id']: s['state_file'] for s in manifest['simulators']}
    for sim_id, derived in _active_sims().items():
        assert declared[sim_id] == derived[0], (
            f'{sim_id}: 매니페스트 {declared[sim_id]} != 클래스 파생 {derived[0]}')


def test_stats_api_covers_every_trading_sim():
    """빠지면 대시보드 카드·레이더에서 그 심이 사라진다."""
    missing = set(EXPECTED.values()) - _state_files(_read(STATS_TS))
    assert not missing, f'stats/route.ts에 누락: {sorted(missing)}'


def test_no_list_references_unknown_state_file():
    """반대 방향 — 심을 지웠는데 목록에 남으면 404를 계속 긁는다.

    분석기(리베로)까지 known에 넣는다. stats/route.ts가 국면 표시용으로
    참조하는 것은 정당하다.
    """
    known = {v[0] for v in _active_sims().values()}
    for label, path in (('sim-reset-targets.ts', RESET_TS),
                        ('daily_brief.py', BRIEF_PY),
                        ('stats/route.ts', STATS_TS)):
        unknown = _state_files(_read(path)) - known
        assert not unknown, f'{label}에 매니페스트에 없는 심: {sorted(unknown)}'
