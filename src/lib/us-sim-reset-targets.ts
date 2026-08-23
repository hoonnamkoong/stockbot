import { US_SIM_REGISTRY } from './us-sim-registry.generated.ts';
import { buildResetState, TRADE_CSV_HEADER as RESET_CSV_HEADER } from './sim-registry.generated.ts';

export interface ResetTarget { id: string; stateFile: string; csvFile: string; }

export const US_RESET_TARGETS: ResetTarget[] = US_SIM_REGISTRY.map((s) => ({
  id: s.uiKey, stateFile: s.stateFile, csvFile: s.csvFile,
}));

export { buildResetState, RESET_CSV_HEADER };

export function validateUsCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 1_000 || cash > 500_000) {
    return { ok: false, error: '예수금은 $1,000 ~ $500,000 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}
