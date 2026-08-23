"""us_strategy_manifest.yaml → src/lib/us-sim-registry.generated.ts.

scripts/gen_sim_registry.py(국내)와 같은 이유로 존재한다 — TS는 'use client'
컴포넌트라 fs로 YAML을 못 읽는다. 국내 생성기·생성 파일은 건드리지 않는다.

    python scripts/gen_us_sim_registry.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.us_registry import get_us_sim_registry  # noqa: E402

OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'src', 'lib', 'us-sim-registry.generated.ts')

HEADER = """// 이 파일은 생성됩니다. 직접 고치지 마세요.
// 원천: src/strategy/us_strategy_manifest.yaml
// 생성: python scripts/gen_us_sim_registry.py

export interface USSimRegistryEntry {
  id: string;
  uiKey: string;
  label: string;
  shortDesc: string;
  color: string;
  chartGroup: number;
  stateFile: string;
  csvFile: string;
  tradeable: boolean;
  currency: string;
}
"""


def _ts(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def build() -> str:
    reg = get_us_sim_registry()
    lines = [HEADER, 'export const US_SIM_REGISTRY: USSimRegistryEntry[] = [']
    for s in reg:
        fields = [
            ('id', s['id']), ('uiKey', s['ui_key']), ('label', s['label']),
            ('shortDesc', s['short_desc']), ('color', s['color']),
            ('chartGroup', s['chart_group']), ('stateFile', s['state_file']),
            ('csvFile', s['csv_file']), ('tradeable', s['tradeable']),
            ('currency', s['currency']),
        ]
        lines.append('  { ' + ', '.join(f'{k}: {_ts(v)}' for k, v in fields) + ' },')
    lines.append('];')
    return '\n'.join(lines)


if __name__ == '__main__':
    content = build()
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    print(f'[gen_us_sim_registry] {os.path.relpath(OUT_PATH)} 갱신 — US 심 {len(get_us_sim_registry())}개')
