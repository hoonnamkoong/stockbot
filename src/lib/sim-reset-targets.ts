export interface ResetTarget { id: string; stateFile: string; csvFile: string; }

export const RESET_TARGETS: ResetTarget[] = [
  { id: 'sim1', stateFile: 'sim_psych_state.json', csvFile: 'trade_history_sim_psych.csv' },
  { id: 'sim2', stateFile: 'sim_spillover_state.json', csvFile: 'trade_history_sim_spillover.csv' },
  { id: 'sim3', stateFile: 'sim_risk_state.json', csvFile: 'trade_history_sim_risk.csv' },
  { id: 'sim4', stateFile: 'sim_bull_state.json', csvFile: 'trade_history_sim_bull.csv' },
  { id: 'sim4_daytrading', stateFile: 'sim_bulldaytrade_state.json', csvFile: 'trade_history_sim_bulldaytrade.csv' },
  { id: 'sim5', stateFile: 'sim_sideways_state.json', csvFile: 'trade_history_sim_sideways.csv' },
  { id: 'sim6', stateFile: 'sim_bear_state.json', csvFile: 'trade_history_sim_bear.csv' },
  { id: 'sim7', stateFile: 'sim_reportfollower_state.json', csvFile: 'trade_history_sim_reportfollower.csv' },
  // 페이퍼 관찰 단계(tradeable: false)지만 상태는 쌓인다 — 리셋 대상이다.
  // 2026-07-28 추가 시 여기 등록이 누락돼 초기화가 이 셋을 건너뛰고 있었다.
  { id: 'sim8', stateFile: 'sim_accumulation_state.json', csvFile: 'trade_history_sim_accumulation.csv' },
  { id: 'sim9', stateFile: 'sim_gapfade_state.json', csvFile: 'trade_history_sim_gapfade.csv' },
  { id: 'sim9_1', stateFile: 'sim_donchian_state.json', csvFile: 'trade_history_sim_donchian.csv' },
  { id: 'sim10', stateFile: 'sim_orchestrator_state.json', csvFile: 'trade_history_sim_orchestrator.csv' },
];

export const RESET_CSV_HEADER = '﻿timestamp,symbol,action,price,quantity,total_amount,reason\n';

export function buildResetState(cash: number): Record<string, unknown> {
  return {
    initial_cash: cash, cash, invested: 0, portfolio: {}, peak_nav: cash,
    total_fees: 0, history: [cash], daily_trades: [],
    market_index_healthy: true, cooldown_codes: {},
  };
}

export function validateCash(cash: unknown): { ok: true; value: number } | { ok: false; error: string } {
  if (typeof cash !== 'number' || !Number.isInteger(cash)) {
    return { ok: false, error: '예수금은 정수여야 합니다' };
  }
  if (cash < 100_000 || cash > 1_000_000_000) {
    return { ok: false, error: '예수금은 10만 ~ 10억 사이여야 합니다' };
  }
  return { ok: true, value: cash };
}
