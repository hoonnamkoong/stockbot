"""매니페스트가 심 목록의 유일한 원천인지 지킨다.

심 목록이 파이썬·TS 여섯 곳에 복제돼 있던 시절 두 번 어긋났다.
  - 2026-07-29: 심8·심9·심9-1이 리셋 목록과 일일 브리프에 없어, 초기화가 셋을
    건너뛰고 15:00 브리프에도 안 나왔다.
  - 2026-07-30: 같은 셋이 매매 기록 API에도 없어, 대시보드 카드의 기록 표가
    영구히 비어 있었다. 그때 이 파일이 *상태 파일*만 대조하고 CSV는 안 봐서 못 잡았다.

지금은 파이썬이 registry.get_sim_registry()로, TS가 생성된 상수로 매니페스트를
읽는다. 그래서 이 테스트가 보는 것은 두 가지다 —
  ① 매니페스트에 적은 값이 코드가 실제로 만드는 값과 같은가(손으로 적는 경로)
  ② 소비자가 자기 목록을 다시 만들지 않았는가(복제의 재발 방지)

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
GENERATED_TS = os.path.join(ROOT, 'src', 'lib', 'sim-registry.generated.ts')

# 심 목록을 소비하는 곳. 여기에 상태·CSV 파일명이 다시 나타나면 복제가 부활한 것이다.
CONSUMERS = {
    'sim-reset-targets.ts': os.path.join(ROOT, 'src', 'lib', 'sim-reset-targets.ts'),
    'daily_brief.py': os.path.join(ROOT, 'src', 'pipeline', 'daily_brief.py'),
    'stats/route.ts': os.path.join(ROOT, 'src', 'app', 'api', 'simulation', 'stats', 'route.ts'),
    'history/route.ts': os.path.join(ROOT, 'src', 'app', 'api', 'trade', 'history', 'route.ts'),
    'StrategyRadarChart.tsx': os.path.join(ROOT, 'src', 'app', 'components', 'StrategyRadarChart.tsx'),
    'TradeClient.tsx': os.path.join(ROOT, 'src', 'app', 'trade', 'TradeClient.tsx'),
    'program/route.ts': os.path.join(ROOT, 'src', 'app', 'api', 'trade', 'program', 'route.ts'),
}


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _manifest_sims():
    """활성 심 블록 그대로(분석기 포함)."""
    return [s for s in yaml.safe_load(_read(MANIFEST))['simulators'] if s.get('active', True)]


def _derived_names():
    """활성 심 → {id: (상태파일, CSV파일, 분석기여부)}. 클래스 소스에서 파생한다."""
    out = {}
    for s in _manifest_sims():
        src = _read(os.path.join(ROOT, *s['module'].split('.')) + '.py')
        m = re.search(r'super\(\)\.__init__\(\s*"([^"]+)"', src)
        assert m, f"{s['id']}: super().__init__(\"Name\") 을 찾지 못했다"
        name = m.group(1).lower()
        out[s['id']] = (f'sim_{name}_state.json',
                        f'trade_history_sim_{name}.csv',
                        'IS_ANALYZER = True' in src)
    return out


DERIVED = _derived_names()


# ── ① 매니페스트에 적은 값 vs 코드가 실제로 만드는 값 ─────────────────────────

def test_manifest_state_file_matches_class_naming_rule():
    """오타 한 글자면 없는 파일을 읽는다 — 그 심의 성과가 조용히 '측정 불가'로 나온다."""
    declared = {s['id']: s['state_file'] for s in _manifest_sims()}
    for sim_id, (state_file, _, _) in DERIVED.items():
        assert declared[sim_id] == state_file, (
            f'{sim_id}: 매니페스트 {declared[sim_id]} != 클래스 파생 {state_file}')


def test_manifest_csv_file_matches_class_naming_rule():
    """CSV가 어긋나면 그 심의 매매 기록 표가 조용히 빈다(2026-07-30에 실제로 그랬다)."""
    declared = {s['id']: s['csv_file'] for s in _manifest_sims()}
    for sim_id, (_, csv_file, _) in DERIVED.items():
        assert declared[sim_id] == csv_file, (
            f'{sim_id}: 매니페스트 {declared[sim_id]} != 클래스 파생 {csv_file}')


def test_manifest_analyzer_flag_matches_class():
    """analyzer 플래그가 어긋나면 매매하지 않는 심이 성과 순위표에 오르거나 그 반대가 된다."""
    declared = {s['id']: bool(s.get('analyzer', False)) for s in _manifest_sims()}
    for sim_id, (_, _, is_analyzer) in DERIVED.items():
        assert declared[sim_id] == is_analyzer, (
            f'{sim_id}: 매니페스트 analyzer={declared[sim_id]} != 클래스 {is_analyzer}')


def test_trading_sims_have_ui_fields():
    """UI 필드가 빠지면 생성기가 죽는다 — 여기서 어느 심의 무슨 필드인지 알려준다."""
    for s in _manifest_sims():
        if s.get('analyzer', False):
            continue
        missing = [k for k in ('ui_key', 'short_desc', 'chart_group', 'color', 'label')
                   if not s.get(k)]
        assert not missing, f"{s['id']}: {missing} 누락"


def test_ui_keys_and_colors_are_unique():
    """ui_key가 겹치면 두 심이 같은 성과를 보고, color가 겹치면 순위표에서 구분이 안 된다."""
    sims = [s for s in _manifest_sims() if not s.get('analyzer', False)]
    for field in ('ui_key', 'color'):
        values = [s[field] for s in sims]
        dupes = {v for v in values if values.count(v) > 1}
        assert not dupes, f'{field} 중복: {sorted(dupes)}'


def test_every_color_has_a_chart_hex():
    """생성된 hex 표에 없는 색을 쓰면 그 심만 회색 선으로 조용히 떨어진다."""
    palette = set(re.findall(r'^\s{2}(\w+): \'#[0-9a-f]{6}\',$', _read(GENERATED_TS), re.M))
    for s in _manifest_sims():
        if s.get('analyzer', False):
            continue
        assert s['color'] in palette, (
            f"{s['id']}: color '{s['color']}'가 SIM_CHART_HEX에 없다 "
            f'(gen_sim_registry.py의 표에 추가할 것). 사용 가능: {sorted(palette)}')


def test_display_order_is_unique():
    """같으면 정렬이 비결정적이 돼 브리프·순위표 순서가 실행마다 흔들릴 수 있다."""
    orders = [s['display_order'] for s in _manifest_sims()]
    assert len(set(orders)) == len(orders), f'display_order 중복: {sorted(orders)}'


# ── ② 소비자가 자기 목록을 다시 만들지 않았는가 ───────────────────────────────

def test_generated_ts_is_up_to_date():
    """매니페스트를 고치고 생성기를 안 돌리면 대시보드만 옛 목록으로 남는다."""
    from scripts.gen_sim_registry import build
    assert build() == _read(GENERATED_TS), (
        'src/lib/sim-registry.generated.ts가 매니페스트와 다르다. '
        'python scripts/gen_sim_registry.py 를 돌리고 커밋할 것.')


def test_consumers_do_not_hardcode_sim_files():
    """복제의 재발 방지 — 소비자에 파일명 리터럴이 나타나면 매니페스트를 안 보는 목록이 생긴 것이다."""
    literal = re.compile(r'sim_[a-z0-9]+_state\.json|trade_history_sim_[a-z0-9]+\.csv')
    for label, path in CONSUMERS.items():
        found = sorted(set(literal.findall(_read(path))))
        assert not found, (
            f'{label}에 심 파일명이 직접 박혀 있다: {found} — '
            '매니페스트에서 파생할 것(파이썬은 registry.get_sim_registry(), '
            'TS는 sim-registry.generated.ts)')


def test_no_ts_file_reads_the_manifest_at_runtime():
    """TS는 매니페스트를 런타임에 받아 파싱하지 않는다 — 생성된 상수를 쓴다.

    manifest-sims.ts가 GitHub main의 매니페스트를 fetch해 정규식으로 긁고 있었다.
    실패하면 빈 배열을 돌려줘서, 사용자가 심을 골라 프로그램 매매를 켜도 선택이
    조용히 null이 됐다(2026-07-30 제거). 게다가 심 이름을 description에서 잘라
    만들어 실전 드롭다운에만 대시보드와 다른 이름이 떴다.

    같은 것이 되살아나면 여기서 걸린다.
    """
    ts_files = []
    for base in ('src/app', 'src/lib'):
        for dirpath, _, names in os.walk(os.path.join(ROOT, base)):
            ts_files += [os.path.join(dirpath, n) for n in names
                         if n.endswith(('.ts', '.tsx'))]
    # 생성 파일 자신은 헤더에 원천 경로를 적는다 — 읽는 게 아니라 출처 표기다.
    offenders = [os.path.relpath(p, ROOT).replace('\\', '/') for p in ts_files
                 if os.path.abspath(p) != os.path.abspath(GENERATED_TS)
                 and 'strategy_manifest' in _read(p)]
    assert not offenders, (
        f'TS가 매니페스트를 직접 읽는다: {offenders} — '
        'src/lib/sim-registry.generated.ts에서 파생할 것')


def test_tradeable_ids_match_python_whitelist():
    """대시보드 드롭다운과 파이프라인 화이트리스트가 같은 집합이어야 한다.

    어긋나면 화면에서 고를 수 있는데 파이썬이 안 돌리는 심(또는 그 반대)이 생긴다.
    """
    from src.strategy.registry import get_tradeable_simulator_ids
    generated = _read(GENERATED_TS)
    # tradeableSims()는 SIM_REGISTRY의 tradeable: true 항목이다.
    ts_ids = {m.group(1) for m in re.finditer(
        r"\{ id: '([^']+)'.*?tradeable: true \}", generated)}
    assert ts_ids == set(get_tradeable_simulator_ids()), (
        f'TS {sorted(ts_ids)} != 파이썬 {sorted(get_tradeable_simulator_ids())}')


def test_daily_brief_derives_from_manifest():
    """브리프는 자체 목록을 갖지 않는다 — 매니페스트에서 파생한다."""
    from src.pipeline.daily_brief import SIM_BRIEF_TARGETS
    expected = {v[0] for k, v in DERIVED.items() if not v[2]}
    assert {t[1] for t in SIM_BRIEF_TARGETS} == expected
    assert 'sim_libero_state.json' not in {t[1] for t in SIM_BRIEF_TARGETS}


def test_brief_is_ordered_for_humans_not_execution():
    """표시 순서는 실행 순서와 분리돼 있다.

    매니페스트 나열 순서는 실행 순서(국면 생산자가 소비자보다 앞)라 사람이
    읽기엔 뒤죽박죽이다(1,2,3,4,5,6,4-1,7,10,8,9,9-1). display_order가 그걸
    번호순으로 되돌린다.

    '무엇이 마지막인가'를 박아두지 않는다 — 심을 하나 붙이면 곧바로 깨지는데
    그건 이 리팩터링이 없애려던 마찰이다. 대신 순서가 display_order를 따르는지,
    그리고 4-1이 4 바로 뒤에 오는지(나열 순서를 그대로 썼다면 4-1은 6 뒤다)를 본다.
    """
    from src.pipeline.daily_brief import SIM_BRIEF_TARGETS
    from src.strategy.registry import get_sim_registry
    labels = [t[0] for t in SIM_BRIEF_TARGETS]
    assert labels == [s['label'] for s in get_sim_registry()]
    assert labels.index('상승 단타형 (Sim 4-1)') == labels.index('상승 모멘텀형 (Sim 4)') + 1


def test_registry_exposes_every_trading_sim():
    """전제 확인 — 매매심이 실제로 잡히는가(0개면 위 대조가 전부 무의미해진다)."""
    from src.strategy.registry import get_sim_registry
    assert len(get_sim_registry()) >= 10
