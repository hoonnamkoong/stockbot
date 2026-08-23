// 이 파일은 생성됩니다. 직접 고치지 마세요.
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

export const US_SIM_REGISTRY: USSimRegistryEntry[] = [
  { id: 'us_sim1_minervini', uiKey: 'us_sim1', label: 'US 미너비니 추세형 (US Sim 1)', shortDesc: '추세 템플릿 + 실적 가속(EPS·매출) + VCP 압축 돌파', color: 'blue', chartGroup: 1, stateFile: 'sim_us1minervini_state.json', csvFile: 'trade_history_sim_us1minervini.csv', tradeable: false, currency: 'USD' },
];