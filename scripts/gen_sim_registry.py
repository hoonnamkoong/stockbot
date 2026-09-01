"""매니페스트·리셋 상태 shape → 대시보드가 읽는 TS 상수를 생성한다.

심 목록이 파이썬과 TS 양쪽에 복제돼 있으면 어긋난다 — 2026-07-29에 심8·심9·심9-1이
리셋·브리프에서, 심8·심9·심9-1의 매매 기록이 히스토리 API에서 각각 누락됐다.
파이썬은 registry.get_sim_registry()로 매니페스트를 읽지만 TS는 그럴 수 없다.
대시보드의 소비자 둘이 'use client' 컴포넌트라 fs로 YAML을 못 읽기 때문이다.

그래서 빌드 타임에 옮긴다. 생성 결과는 커밋한다(런타임 의존 0). 매니페스트를
고치고 이 스크립트를 안 돌리면 tests/test_sim_registry_consistency.py가 잡는다.

리셋 상태 shape도 같은 이유로 여기서 나온다 — 대시보드의 리셋 버튼이 파이썬과
같은 10키 JSON을 써야 하는데, 손으로 두 벌 적으면 한쪽에 키가 늘어도 아무도 모른다.
정본은 base_simulator.initial_state()다.

    python scripts/gen_sim_registry.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.strategy.registry import get_sim_registry  # noqa: E402
from src.strategy.simulators.base_simulator import (  # noqa: E402
    CSV_HEADER, DEFAULT_INITIAL_CASH, initial_state)

OUT_PATH = os.path.join(os.path.dirname(__file__), '..', 'src', 'lib', 'sim-registry.generated.ts')

HEADER = """// 이 파일은 생성됩니다. 직접 고치지 마세요.
// 원천: src/strategy/strategy_manifest.yaml
// 생성: python scripts/gen_sim_registry.py
//
// 심을 추가·삭제·변경하려면 매니페스트를 고치고 위 명령을 다시 돌리세요.
// 안 돌리면 tests/test_sim_registry_consistency.py가 실패합니다.

export interface SimRegistryEntry {
  /** 매니페스트 id. 매매 기록 API가 각 행에 붙이는 type 값이다. */
  id: string;
  /** 통계 API 응답의 키. 대시보드가 성과를 찾는 이름. */
  uiKey: string;
  label: string;
  shortDesc: string;
  /** Mantine 팔레트 이름. 카드는 그대로 쓰고, 차트는 SIM_CHART_HEX로 hex를 얻는다. */
  color: string;
  chartGroup: number;
  stateFile: string;
  csvFile: string;
  /** 프로그램 매매 노출 여부. false면 페이퍼 관찰 단계다. */
  tradeable: boolean;
}
"""

FOOTER = """
/** 관찰 단계(tradeable: false) — 순위표에서 실전 심과 구분해 표시한다. */
export function isPaper(s: SimRegistryEntry): boolean {
  return !s.tradeable;
}

/**
 * 프로그램 매매에 노출할 심(active && tradeable). 실전 드롭다운과 화이트리스트 검증의 원천.
 *
 * 예전에는 manifest-sims.ts가 GitHub main의 매니페스트를 런타임에 받아 정규식으로 긁었다.
 * 조회가 실패하면 빈 배열을 돌려줘서, 사용자가 심을 골라 ON을 눌러도 선택이 조용히
 * 버려졌다. 이제 네트워크가 관여하지 않는다.
 */
export function tradeableSims(): SimRegistryEntry[] {
  return SIM_REGISTRY.filter((s) => s.tradeable);
}

export function simsInChartGroup(group: number): SimRegistryEntry[] {
  return SIM_REGISTRY.filter((s) => s.chartGroup === group);
}

/**
 * Mantine 팔레트 이름 → hex. recharts는 CSS 변수를 못 받아 hex가 필요하다.
 *
 * shade 7을 쓴다: 카드 테두리(--mantine-color-{name}-filled = shade 6)보다 한 단계
 * 진해 흰 배경의 얇은 선에서도 읽힌다. 같은 색상 계열이라 카드와 차트가 붙는다.
 */
export const SIM_CHART_HEX: Record<string, string> = {
  blue: '#1c7ed6',
  violet: '#7048e8',
  red: '#f03e3e',
  green: '#37b24d',
  teal: '#0ca678',
  yellow: '#f59f00',
  cyan: '#1098ad',
  pink: '#d6336c',
  indigo: '#4263eb',
  orange: '#f76707',
  lime: '#74b816',
  grape: '#ae3ec9',
  gray: '#495057',
  dark: '#1a1b1e',
  // Mantine 기본 팔레트(14색)가 Sim12에서 완전히 소진됐다(위 dark 주석 참고).
  // Sim13부터는 리터럴 hex 문자열을 이름 대신 그대로 키·color 값으로 쓴다 —
  // theme.colors에 등록된 이름이 아니어도 Mantine의 color prop은 유효한 CSS
  // 색상값을 그대로 받아들인다(공식 지원 동작). shade 자동계산(filled/light
  // variant의 밝기 단계)은 못 받지만 Badge/Text 등에서 문제없이 렌더된다.
  '#a1662f': '#a1662f',
};

export function chartHex(s: SimRegistryEntry): string {
  return SIM_CHART_HEX[s.color] ?? '#868e96';
}
"""


class _Cash:
    """예수금 자리표시자. 직렬화될 때 TS 식별자 `cash`로 바뀐다."""


_CASH_MARKER = '@@CASH@@'


def _reset_state_ts() -> str:
    """base_simulator.initial_state()의 dict를 TS 함수 본문으로 옮긴다.

    예수금에서 파생되는 값(initial_cash·cash·peak_nav·history[0])이 무엇인지
    여기에 다시 적지 않는다 — 자리표시자를 넣고 부르면 파이썬이 그것을 어디에
    놓든 그 자리에 `cash`가 찍힌다. 파이썬이 예수금 파생 필드를 하나 더 늘려도
    이 생성기는 고칠 것이 없다.
    """
    dumped = json.dumps(initial_state(_Cash()), indent=2, ensure_ascii=False,
                        default=lambda o: _CASH_MARKER)
    body = '\n'.join('  ' + line for line in dumped.split('\n')).strip()
    body = body.replace(f'"{_CASH_MARKER}"', 'cash')
    return (
        '/**\n'
        ' * 리셋 직후의 상태. 파이썬 base_simulator.initial_state()에서 생성됐다.\n'
        ' *\n'
        ' * 대시보드 리셋과 파이프라인 리셋이 같은 shape를 써야 한다 — 예전에는 양쪽이\n'
        ' * 손으로 같은 10키를 적고 있어서, 한쪽에 키가 늘면 대시보드로 리셋한 심만\n'
        ' * 다른 상태로 시작하고 아무도 몰랐다.\n'
        ' */\n'
        'export function buildResetState(cash: number): Record<string, unknown> {\n'
        f'  return {body};\n'
        '}'
    )


def _initial_cash_ts() -> str:
    """base_simulator.DEFAULT_INITIAL_CASH를 TS 상수로 옮긴다.

    2026-09-01까지 이 값이 파이썬 16곳(각 심의 __init__ 기본값)과 TS 4곳에
    각각 박혀 있었고, 기반 클래스 기본값만 5,000,000으로 달랐다.

    분모가 갈리면 대시보드와 텔레그램이 **다른 수익률**을 말한다. 그 사고는
    이미 한 번 났다(리셋 예수금 200만 전환). CSV 헤더를 여기서 생성하는 것과
    같은 이유다 — 손으로 적으면 한쪽만 바뀐다.
    """
    return (
        '/** 심 초기자본. 원천은 파이썬 base_simulator.DEFAULT_INITIAL_CASH다. */\n'
        f'export const SIM_INITIAL_CASH = {DEFAULT_INITIAL_CASH};'
    )


def _csv_header_ts() -> str:
    """base_simulator.CSV_HEADER를 TS 상수로 옮긴다.

    대시보드 리셋이 새로 만드는 빈 CSV의 헤더다. 손으로 적던 시절 파이썬이
    roi 열을 늘렸을 때 이쪽이 구 헤더로 남아, 대시보드로 리셋한 심만 ROI를
    기록하지 못하는 상태가 됐다.

    BOM은 파이썬 기록기가 utf-8-sig로 쓰기 때문이다(엑셀 호환).
    """
    return (
        '/** 매매 기록 CSV의 헤더. 파이썬 base_simulator.CSV_HEADER에서 생성됐다. */\n'
        "export const TRADE_CSV_HEADER = '\\ufeff" + ','.join(CSV_HEADER) + "\\n';"
    )


def _ts(value) -> str:
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    return "'" + str(value).replace('\\', '\\\\').replace("'", "\\'") + "'"


def build() -> str:
    trading = get_sim_registry()
    analyzers = [s for s in get_sim_registry(include_analyzers=True) if s['analyzer']]

    lines = [HEADER, 'export const SIM_REGISTRY: SimRegistryEntry[] = [']
    for s in trading:
        fields = [
            ('id', s['id']), ('uiKey', s['ui_key']), ('label', s['label']),
            ('shortDesc', s['short_desc']), ('color', s['color']),
            ('chartGroup', s['chart_group']), ('stateFile', s['state_file']),
            ('csvFile', s['csv_file']), ('tradeable', s['tradeable']),
        ]
        lines.append('  { ' + ', '.join(f'{k}: {_ts(v)}' for k, v in fields) + ' },')
    lines.append('];')

    lines.append('')
    lines.append('/** 국면 분석기(매매 없음). 성과 목록에 오르지 않고 국면 표시로만 쓰인다. */')
    lines.append('export const ANALYZERS: { id: string; stateFile: string }[] = [')
    for s in analyzers:
        lines.append(f"  {{ id: {_ts(s['id'])}, stateFile: {_ts(s['state_file'])} }},")
    lines.append('];')

    lines.append('')
    lines.append(_initial_cash_ts())

    lines.append('')
    lines.append(_csv_header_ts())

    lines.append('')
    lines.append(_reset_state_ts())

    lines.append(FOOTER)
    return '\n'.join(lines)


if __name__ == '__main__':
    content = build()
    with open(OUT_PATH, 'w', encoding='utf-8', newline='\n') as f:
        f.write(content)
    print(f'[gen_sim_registry] {os.path.relpath(OUT_PATH)} 갱신 — 매매심 {len(get_sim_registry())}개')
