// 확장자를 붙인다: 이 모듈은 node --experimental-strip-types --test 로도 로드되는데
// (sim-reset-targets.test.ts) node의 ESM 해석기는 확장자 없는 상대경로를 못 찾는다.
import { SIM_REGISTRY } from './sim-registry.generated.ts';

export interface ResetTarget { id: string; stateFile: string; csvFile: string; }

// 매매하는 활성 심 전부가 리셋 대상이다 — 페이퍼 관찰 단계(tradeable: false)도
// 상태는 쌓이므로 포함된다. 목록을 여기 손으로 적던 시절 2026-07-28에 추가한
// 심8·심9·심9-1이 누락돼 초기화가 셋을 건너뛰고 있었다.
export const RESET_TARGETS: ResetTarget[] = SIM_REGISTRY.map((s) => ({
  id: s.uiKey,
  stateFile: s.stateFile,
  csvFile: s.csvFile,
}));

export const RESET_CSV_HEADER = '﻿timestamp,symbol,action,price,quantity,total_amount,reason\n';

// 리셋 상태 shape는 여기서 만들지 않는다 — 파이썬 base_simulator.initial_state()가
// 정본이고 생성기가 옮겨 적는다. 손으로 두 벌 적으면 한쪽에 키가 늘어도 아무도 모른다.
export { buildResetState } from './sim-registry.generated.ts';

export function validateCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 100_000 || cash > 1_000_000_000) {
    return { ok: false, error: '예수금은 10만 ~ 10억 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}
