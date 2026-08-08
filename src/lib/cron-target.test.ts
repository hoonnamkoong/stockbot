import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync, existsSync } from 'node:fs';
import { pickWorkflow, TOKEN_REFRESH_HOUR_KST } from './cron-target.ts';

// 태스커 → /api/cron → workflow_dispatch. 대상 워크플로가 실재하지 않거나
// 엉뚱한 것을 가리키면 **아무 것도 실패하지 않고** 봇이 멈춘다. 실행 이력이
// 0건인 워크플로는 어떤 실패 목록에도 안 뜬다(2026-08-07에 하루를 그렇게 잃었다).

test('장중 트리거는 매매 워크플로로 간다', () => {
  for (const hour of [9, 10, 12, 14, 15]) {
    assert.equal(pickWorkflow(hour), 'trading.yml', `${hour}시`);
  }
});

test('장 시작 전 한 시간만 토큰 선발급으로 분기한다', () => {
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST), 'token_refresh.yml');
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST + 1), 'trading.yml');
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST - 1), 'trading.yml');
});

test('스크래퍼는 태스커가 직접 부르지 않는다', () => {
  // scraper.yml은 trading.yml이 10분 격자에서 깨운다. 여기서 부르면 매매가
  // 통째로 멈춘다 — 스크래퍼는 자기를 부르지 않기 때문이다.
  for (let hour = 0; hour < 24; hour++) {
    assert.notEqual(pickWorkflow(hour), 'scraper.yml', `${hour}시에 스크래퍼로 간다`);
  }
});

test('dispatch 대상 워크플로가 실제로 존재한다', () => {
  // 이 테스트가 08-07 사고를 잡는 것이다. 그때는 위임 대상 워크플로가
  // 파일로는 존재했지만 트리거가 도달할 수 없었고, 단위 테스트는 "위임한다"만
  // 검증했다. 최소한 파일 존재는 여기서 막는다.
  const targets = new Set<string>();
  for (let hour = 0; hour < 24; hour++) targets.add(pickWorkflow(hour));

  for (const file of targets) {
    assert.ok(
      existsSync(`.github/workflows/${file}`),
      `dispatch 대상 ${file}이 레포에 없다`
    );
  }
});

test('대상 워크플로가 workflow_dispatch를 받아들인다', () => {
  // /api/cron은 workflow_dispatch API를 쓴다. 워크플로에 그 트리거가 없으면
  // GitHub이 422를 돌려주고, 라우트 로그에만 남는다.
  const targets = new Set<string>();
  for (let hour = 0; hour < 24; hour++) targets.add(pickWorkflow(hour));

  for (const file of targets) {
    const yml = readFileSync(`.github/workflows/${file}`, 'utf-8');
    const onBlock = yml.split(/^jobs:/m)[0];
    assert.ok(
      /^\s*workflow_dispatch:/m.test(onBlock),
      `${file}에 workflow_dispatch 트리거가 없다 — dispatch가 422로 실패한다`
    );
  }
});
