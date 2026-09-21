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

// 리셋 상태 shape도 CSV 헤더도 여기서 만들지 않는다 — 파이썬(base_simulator)이
// 정본이고 생성기가 옮겨 적는다. 손으로 두 벌 적으면 한쪽에 키가 늘어도 아무도 모른다.
// 실제로 그랬다: 파이썬이 roi 열을 늘렸는데 여기 헤더는 구 포맷으로 남아 있었다.
export { buildResetState, TRADE_CSV_HEADER as RESET_CSV_HEADER } from './sim-registry.generated.ts';

export function validateCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 100_000 || cash > 1_000_000_000) {
    return { ok: false, error: '예수금은 10만 ~ 10억 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}

// 리셋 표지. 리셋과 같은 커밋에 쓴다 — db-data writer들이 배포 직전에 런 시작 때
// 본 값과 비교해, 런 도중 리셋이 들어왔으면 여기 적힌 파일을 올리지 않는다
// (scripts/reset_epoch_guard.py). 2026-09-17 리셋을 2분 뒤 trading 배포가 런 시작
// 시점 사본으로 되돌려 14개 심 중 10개가 리셋 전 값으로 돌아갔다.
export const RESET_EPOCH_FILE = 'sim_reset_epoch.json';

export function buildResetEpoch(cash: number, files: string[], now: Date = new Date()) {
  return { reset_id: now.toISOString(), cash, files };
}
