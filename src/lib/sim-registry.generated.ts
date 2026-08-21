// 이 파일은 생성됩니다. 직접 고치지 마세요.
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

export const SIM_REGISTRY: SimRegistryEntry[] = [
  { id: 'sim_psych', uiKey: 'sim1', label: '심리 괴리형 (Sim 1)', shortDesc: 'Buzz 급증·가격 정체 종목 매집', color: 'blue', chartGroup: 1, stateFile: 'sim_psych_state.json', csvFile: 'trade_history_sim_psych.csv', tradeable: true },
  { id: 'sim_spillover', uiKey: 'sim2', label: '수급 동승형 (Sim 2)', shortDesc: '외인 수급 + 감정 발산 스코어', color: 'violet', chartGroup: 1, stateFile: 'sim_spillover_state.json', csvFile: 'trade_history_sim_spillover.csv', tradeable: true },
  { id: 'sim_risk', uiKey: 'sim3', label: '가치 페어형 (Sim 3)', shortDesc: '추세 돌파 / 횡보 반등 + 트레일링', color: 'red', chartGroup: 1, stateFile: 'sim_risk_state.json', csvFile: 'trade_history_sim_risk.csv', tradeable: true },
  { id: 'sim4_bull', uiKey: 'sim4', label: '상승 모멘텀형 (Sim 4)', shortDesc: '주도주 탑승·불타기, 고정익절 없이 라이딩', color: 'green', chartGroup: 2, stateFile: 'sim_bull_state.json', csvFile: 'trade_history_sim_bull.csv', tradeable: true },
  { id: 'sim4_bull_daytrading', uiKey: 'sim4_daytrading', label: '상승 단타형 (Sim 4-1)', shortDesc: '상승률 상위 단기 회전 — 분할 익절(+5%/+10%) · 2일/5일 강제청산', color: 'teal', chartGroup: 2, stateFile: 'sim_bulldaytrade_state.json', csvFile: 'trade_history_sim_bulldaytrade.csv', tradeable: true },
  { id: 'sim5_sideways', uiKey: 'sim5', label: '추세 눌림목형 (Sim 5)', shortDesc: '20일 채널 저점 +3% 이내 진입 · 상단 근접 후 트레일링', color: 'yellow', chartGroup: 2, stateFile: 'sim_sideways_state.json', csvFile: 'trade_history_sim_sideways.csv', tradeable: true },
  { id: 'sim6_bear', uiKey: 'sim6', label: '하락 줍줍형 (Sim 6)', shortDesc: 'KODEX 인버스 추세추종 (Sim0 BEAR 게이트) · 트레일링 -10%', color: 'cyan', chartGroup: 3, stateFile: 'sim_bear_state.json', csvFile: 'trade_history_sim_bear.csv', tradeable: true },
  { id: 'sim7_report_follower', uiKey: 'sim7', label: '리포트 팔로워 (Sim 7)', shortDesc: '딥다이브 강력 매수 종목 자동 매수 · 트레일링 라이딩', color: 'pink', chartGroup: 3, stateFile: 'sim_reportfollower_state.json', csvFile: 'trade_history_sim_reportfollower.csv', tradeable: true },
  { id: 'sim8_accumulation', uiKey: 'sim8', label: '선행 매집형 (Sim 8)', shortDesc: '52주 앵커 구간 외인·기관 선매수 포착 + 매집/돌파 2단 피라미딩', color: 'indigo', chartGroup: 3, stateFile: 'sim_accumulation_state.json', csvFile: 'trade_history_sim_accumulation.csv', tradeable: false },
  { id: 'sim9_gap_fade', uiKey: 'sim9', label: '갭소진 반등 (Sim 9)', shortDesc: '갭 +7% 후 장중 -6% 저가권 마감을 14:30~15:20 매수 · 익일 청산', color: 'orange', chartGroup: 4, stateFile: 'sim_gapfade_state.json', csvFile: 'trade_history_sim_gapfade.csv', tradeable: false },
  { id: 'sim9_1_donchian', uiKey: 'sim9_1', label: '돈치안 돌파 (Sim 9-1)', shortDesc: '20일 채널 상단 돌파 추종 · 10일 채널 이탈 / 2ATR 청산', color: 'lime', chartGroup: 4, stateFile: 'sim_donchian_state.json', csvFile: 'trade_history_sim_donchian.csv', tradeable: false },
  { id: 'sim10_orchestrator', uiKey: 'sim10', label: '오케스트레이터 (Sim 10)', shortDesc: 'Sim0 국면에 따라 전략 파라미터 동적 전환 · 300만 독립 운용', color: 'grape', chartGroup: 4, stateFile: 'sim_orchestrator_state.json', csvFile: 'trade_history_sim_orchestrator.csv', tradeable: true },
  { id: 'sim11_minervini', uiKey: 'sim11', label: '미너비니 추세형 (Sim 11)', shortDesc: '추세 템플릿 + 실적 가속(EPS·매출) + VCP 압축 돌파', color: 'gray', chartGroup: 5, stateFile: 'sim_minervini_state.json', csvFile: 'trade_history_sim_minervini.csv', tradeable: false },
  { id: 'sim12_regime_dual', uiKey: 'sim12', label: '국면이원 반등/추세형 (Sim 12)', shortDesc: 'BULL=모멘텀 지속 / SIDEWAYS·BEAR=급락반등(거래대금+기관수급 확인)', color: 'dark', chartGroup: 5, stateFile: 'sim_regimedual_state.json', csvFile: 'trade_history_sim_regimedual.csv', tradeable: false },
  { id: 'sim13_theme_cascade', uiKey: 'sim13', label: '테마 캐스케이드 (Sim 13)', shortDesc: '테마모멘텀+ADX/거래대금서프라이즈+외국인수급 이벤트탐지, PER게이트+그룹집중상한', color: '#a1662f', chartGroup: 5, stateFile: 'sim_themecascade_state.json', csvFile: 'trade_history_sim_themecascade.csv', tradeable: false },
];

/** 국면 분석기(매매 없음). 성과 목록에 오르지 않고 국면 표시로만 쓰인다. */
export const ANALYZERS: { id: string; stateFile: string }[] = [
  { id: 'sim0_libero', stateFile: 'sim_libero_state.json' },
];

/** 매매 기록 CSV의 헤더. 파이썬 base_simulator.CSV_HEADER에서 생성됐다. */
export const TRADE_CSV_HEADER = '\ufefftimestamp,symbol,action,price,quantity,total_amount,reason,roi,roi_amount\n';

/**
 * 리셋 직후의 상태. 파이썬 base_simulator.initial_state()에서 생성됐다.
 *
 * 대시보드 리셋과 파이프라인 리셋이 같은 shape를 써야 한다 — 예전에는 양쪽이
 * 손으로 같은 10키를 적고 있어서, 한쪽에 키가 늘면 대시보드로 리셋한 심만
 * 다른 상태로 시작하고 아무도 몰랐다.
 */
export function buildResetState(cash: number): Record<string, unknown> {
  return {
    "initial_cash": cash,
    "cash": cash,
    "invested": 0,
    "portfolio": {},
    "peak_nav": cash,
    "total_fees": 0,
    "history": [
      cash
    ],
    "daily_trades": [],
    "cooldown_codes": {}
  };
}

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
