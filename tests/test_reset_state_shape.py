"""리셋 직후의 상태 shape가 파이썬과 대시보드에서 같은지 지킨다.

심을 초기화하는 경로가 둘이다 — 파이프라인(`base_simulator.reset_state()`)과
대시보드 리셋 버튼(`/api/simulation/reset` → `buildResetState`). 예전에는 양쪽이
같은 10키를 손으로 각각 적고 있어서, 한쪽에 키가 늘면 **대시보드로 리셋한 심만
다른 상태로 시작하고 아무도 몰랐다.**

지금은 `initial_state()`가 정본이고 `scripts/gen_sim_registry.py`가 TS를 만든다.
여기서 보는 것은 셋이다 —
  ① reset_state()가 정말 그 정본을 쓰는가(인라인 dict로 되돌아가지 않았는가)
  ② 생성된 TS가 같은 키·같은 값을 만드는가
  ③ 소비자(sim-reset-targets.ts)가 shape를 다시 만들지 않는가
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.simulators.base_simulator import BaseSimulator, initial_state  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..')
GENERATED_TS = os.path.join(ROOT, 'src', 'lib', 'sim-registry.generated.ts')
RESET_TARGETS_TS = os.path.join(ROOT, 'src', 'lib', 'sim-reset-targets.ts')


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _isolated_sim(tmp_path, cash):
    """운영 data/ 를 건드리지 않는 인스턴스.

    __init__은 data_dir을 자기 위치에서 계산하고 곧바로 load_state()까지 한다.
    경로를 주입할 틈이 없어 생성자를 건너뛰고 필요한 속성만 채운다.
    """
    sim = BaseSimulator.__new__(BaseSimulator)
    sim.name = 'ShapeTest'
    sim.initial_cash = cash
    sim.state_file = os.path.join(tmp_path, 'sim_shapetest_state.json')
    sim.log_file = os.path.join(tmp_path, 'sim_shapetest_log.json')
    sim.csv_file = os.path.join(tmp_path, 'trade_history_sim_shapetest.csv')
    return sim


def _generated_reset_state(cash):
    """생성된 TS의 buildResetState(cash)를 파이썬 dict로 되읽는다.

    본문은 `cash` 식별자만 빼면 JSON이다. 따옴표 안의 "cash"(키)는 건드리지
    않고 벌거벗은 토큰만 값으로 바꾼다.
    """
    m = re.search(
        r'export function buildResetState\(cash: number\): Record<string, unknown> \{\r?\n'
        r'  return (\{.*?\});\r?\n\}',
        _read(GENERATED_TS), re.S)
    assert m, 'sim-registry.generated.ts에 buildResetState가 없다 — 생성기를 돌렸는가?'
    return json.loads(re.sub(r'(?<![\w"])cash(?![\w"])', str(cash), m.group(1)))


def test_reset_state_uses_the_single_source(tmp_path):
    """reset_state가 dict를 다시 인라인으로 적으면 여기서 걸린다."""
    sim = _isolated_sim(str(tmp_path), 3_000_000)
    sim.reset_state()
    assert sim.state == initial_state(3_000_000)


def test_reset_state_writes_the_same_shape_to_disk(tmp_path):
    """파일로 나간 것도 같은가 — 대시보드가 읽는 것은 이 JSON이다."""
    sim = _isolated_sim(str(tmp_path), 3_000_000)
    sim.reset_state()
    with open(sim.state_file, encoding='utf-8') as f:
        assert json.load(f) == initial_state(3_000_000)


def test_generated_ts_reset_state_equals_python(tmp_path):
    """대시보드 리셋과 파이프라인 리셋이 같은 상태를 만든다.

    키만이 아니라 값까지 본다 — 예전 TS는 history를 [cash]로 적었지만,
    거기서 한 글자만 달라도(예: []) 그 심의 성과 그래프가 다른 원점에서 시작한다.
    """
    assert _generated_reset_state(3_000_000) == initial_state(3_000_000)


def test_generated_ts_derives_every_cash_field(tmp_path):
    """예수금 파생 필드가 상수로 굳지 않았는가.

    자리표시자 치환이 잘못되면 initial_cash·peak_nav가 특정 숫자로 박힌 채
    생성될 수 있다. 다른 예수금으로 한 번 더 본다.
    """
    assert _generated_reset_state(777_777) == initial_state(777_777)


def test_reset_targets_ts_does_not_redefine_the_shape():
    """복제의 재발 방지 — TS가 자기 손으로 상태 키를 적기 시작하면 잡는다."""
    src = _read(RESET_TARGETS_TS)
    # 'cash'만 빼고 본다 — validateCash(cash: ...)의 파라미터 이름과 구분이 안 되는
    # 일반어라서다. 나머지 아홉은 이 shape 말고는 쓸 데가 없다.
    offenders = [k for k in initial_state(0) if k != 'cash'
                 and (f'{k}:' in src or f'"{k}"' in src)]
    assert not offenders, (
        f'sim-reset-targets.ts가 리셋 상태 키를 직접 적고 있다: {offenders} — '
        'base_simulator.initial_state()를 고치고 python scripts/gen_sim_registry.py 를 돌릴 것')
