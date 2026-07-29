import { test } from 'node:test';
import assert from 'node:assert';
import { SIM_REGISTRY, tradeableSims, isPaper, simsInChartGroup, chartHex } from './sim-registry.generated.ts';

// 이 파일은 생성물이다(scripts/gen_sim_registry.py). 매니페스트와의 대조는
// tests/test_sim_registry_consistency.py가 하고, 여기서는 TS 소비자가 기대는
// 형태 불변식만 본다 — 특히 '조용히 비는' 경우.

test('매매 가능 심 목록은 비지 않는다', () => {
  // 이 목록이 비면 실전 프로그램 매매 드롭다운이 텅 비고, 사용자가 심을 골라
  // ON을 눌러도 화이트리스트 검증에서 걸려 선택이 조용히 버려진다.
  // 예전 manifest-sims.ts가 GitHub 조회 실패 시 정확히 그렇게 동작했다.
  assert.ok(tradeableSims().length > 0, '매매 가능 심이 하나도 없다');
});

test('매매 가능 심은 전부 tradeable이고 전체 목록의 부분집합', () => {
  const all = new Set(SIM_REGISTRY.map((s) => s.id));
  for (const s of tradeableSims()) {
    assert.equal(s.tradeable, true, `${s.id}: tradeable이 아니다`);
    assert.ok(all.has(s.id), `${s.id}: SIM_REGISTRY에 없다`);
    assert.equal(isPaper(s), false, `${s.id}: 관찰 단계인데 매매 가능으로 나온다`);
  }
});

test('id와 ui_key가 각각 유일하다', () => {
  for (const key of ['id', 'uiKey'] as const) {
    const vals = SIM_REGISTRY.map((s) => s[key]);
    assert.equal(new Set(vals).size, vals.length, `${key} 중복`);
  }
});

test('모든 심에 라벨과 파일명이 채워져 있다', () => {
  for (const s of SIM_REGISTRY) {
    assert.ok(s.label.length > 0, `${s.id}: label 비어 있음`);
    assert.match(s.stateFile, /^sim_[a-z0-9]+_state\.json$/, `${s.id}: stateFile`);
    assert.match(s.csvFile, /^trade_history_sim_[a-z0-9]+\.csv$/, `${s.id}: csvFile`);
  }
});

test('차트 그룹이 전체를 빠짐없이 덮는다', () => {
  // 그룹에서 빠진 심은 레이더 차트 어디에도 안 그려진다 — 조용한 부재다.
  const grouped = new Set(
    [1, 2, 3, 4].flatMap((g) => simsInChartGroup(g)).map((s) => s.id),
  );
  const missing = SIM_REGISTRY.filter((s) => !grouped.has(s.id)).map((s) => s.id);
  assert.deepEqual(missing, [], `차트 그룹 1~4 어디에도 없는 심: ${missing}`);
});

test('모든 심의 색이 hex로 풀린다 — 폴백 회색으로 떨어지지 않는다', () => {
  const FALLBACK = '#868e96';
  for (const s of SIM_REGISTRY) {
    assert.notEqual(chartHex(s), FALLBACK, `${s.id}: color '${s.color}'가 표에 없다`);
  }
});
