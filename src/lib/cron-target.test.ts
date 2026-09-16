import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync, existsSync } from 'node:fs';
import {
  pickWorkflow,
  pickSideWorkflows,
  TOKEN_REFRESH_HOUR_KST,
  HEARTBEAT_WORKFLOW,
} from './cron-target.ts';

// 태스커 → /api/cron → workflow_dispatch. 대상 워크플로가 실재하지 않거나
// 엉뚱한 것을 가리키면 **아무 것도 실패하지 않고** 봇이 멈춘다. 실행 이력이
// 0건인 워크플로는 어떤 실패 목록에도 안 뜬다(2026-08-07에 하루를 그렇게 잃었다).

/** 태스커 트리거가 도달할 수 있는 모든 워크플로 — 주 대상과 부수 대상 둘 다. */
function allTargets(): Set<string> {
  const targets = new Set<string>();
  for (let hour = 0; hour < 24; hour++)
    for (let minute = 0; minute < 60; minute++) {
      targets.add(pickWorkflow(hour, minute));
      for (const f of pickSideWorkflows(hour, minute)) targets.add(f);
    }
  return targets;
}

test('장중 트리거는 매매 워크플로로 간다', () => {
  for (const hour of [9, 10, 12, 14, 15]) {
    assert.equal(pickWorkflow(hour, 0), 'trading.yml', `${hour}시`);
  }
});

test('장 시작 전 첫 틱만 토큰 선발급으로 분기한다', () => {
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST, 0), 'token_refresh.yml');
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST, 2), 'trading.yml');
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST + 1, 0), 'trading.yml');
  assert.equal(pickWorkflow(TOKEN_REFRESH_HOUR_KST - 1, 0), 'trading.yml');
});

test('스크래퍼는 태스커가 직접 부르지 않는다', () => {
  // scraper.yml은 trading.yml이 10분 격자에서 깨운다. 여기서 부르면 매매가
  // 통째로 멈춘다 — 스크래퍼는 자기를 부르지 않기 때문이다.
  for (let hour = 0; hour < 24; hour++) {
    assert.notEqual(pickWorkflow(hour, 0), 'scraper.yml', `${hour}시에 스크래퍼로 간다`);
  }
});

test('dispatch 대상 워크플로가 실제로 존재한다', () => {
  // 이 테스트가 08-07 사고를 잡는 것이다. 그때는 위임 대상 워크플로가
  // 파일로는 존재했지만 트리거가 도달할 수 없었고, 단위 테스트는 "위임한다"만
  // 검증했다. 최소한 파일 존재는 여기서 막는다.
  const targets = allTargets();

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
  const targets = allTargets();

  for (const file of targets) {
    const yml = readFileSync(`.github/workflows/${file}`, 'utf-8');
    const onBlock = yml.split(/^jobs:/m)[0];
    assert.ok(
      /^\s*workflow_dispatch:/m.test(onBlock),
      `${file}에 workflow_dispatch 트리거가 없다 — dispatch가 422로 실패한다`
    );
  }
});

test('07시대 2분 격자 전체에서 토큰 선발급은 딱 한 번만 나간다', () => {
  // 태스커는 /api/cron을 2분마다 부른다. 시(hour)만 보고 분기하면 07시대
  // 30틱이 전부 token_refresh.yml로 가서 KIS 토큰이 2분마다 강제 재발급된다
  // (2026-09-02 07:00~07:50 실측 26건). 동시에 그 한 시간의 매매 트리거가
  // 통째로 사라진다.
  const dispatched: string[] = [];
  for (let minute = 0; minute < 60; minute += 2) {
    dispatched.push(pickWorkflow(TOKEN_REFRESH_HOUR_KST, minute));
  }

  assert.equal(
    dispatched.filter((f) => f === 'token_refresh.yml').length,
    1,
    `07시대 토큰 발급 횟수: ${dispatched.filter((f) => f === 'token_refresh.yml').length}`
  );
  assert.equal(dispatched.filter((f) => f === 'trading.yml').length, 29);
});


// ── 장중 생존 감시(heartbeat_watch.yml) 발화 ────────────────────────────
// 네이티브 cron(`0 0-6 * * 1-5`)은 세션당 7회를 기대하는데 6거래일 실측 발화는
// 하루 2회였고(12/42) 뒤엣것은 전부 장 마감 뒤라 off_session이었다 —
// **장중 유효 커버리지 6/42 = 14.3%.** 이 레포에서 시간당 1회도 고빈도다.
// 창·격자가 장중과 어긋났는지는 tests/test_heartbeat_dispatch_window.py가
// 파이썬 판정(src/heartbeat.py)과 대조해 지킨다.

test('감시 발화는 매매 트리거를 대체하지 않는다', () => {
  // 부수 대상으로 둔 이유가 이것이다. pickWorkflow를 갈라 감시로 보내면
  // 그 틱의 매매 트리거가 사라진다 — 07시대에 이미 겪은 모양이다.
  for (let hour = 0; hour < 24; hour++)
    for (let minute = 0; minute < 60; minute++)
      assert.ok(
        !pickSideWorkflows(hour, minute).includes(pickWorkflow(hour, minute)),
        `${hour}:${minute}에 주 대상과 부수 대상이 같다`
      );
});

test('감시는 장 밖에서 깨우지 않는다', () => {
  for (const [hour, minute] of [[7, 0], [8, 30], [9, 0], [16, 0], [22, 10], [3, 0]]) {
    assert.deepEqual(
      pickSideWorkflows(hour, minute), [],
      `${hour}:${minute}에 감시를 깨운다 — off_session으로 헛돈다`
    );
  }
});

test('감시는 2분 격자의 어느 위상에서도 세션당 12회 이상 깨어난다', () => {
  // 태스커 격자가 짝수 분에 놓일지 홀수 분에 놓일지는 폰 프로파일이 정하고
  // 코드는 모른다. `minute % 15 === 0`처럼 정각만 보는 조건은 격자가 홀수
  // 위상일 때 **한 번도 안 걸린다** — 발화 0회가 조용히 된다.
  for (const phase of [0, 1]) {
    const fired: number[] = [];
    for (let hour = 0; hour < 24; hour++)
      for (let minute = phase; minute < 60; minute += 2)
        if (pickSideWorkflows(hour, minute).includes(HEARTBEAT_WORKFLOW))
          fired.push(hour * 60 + minute);

    assert.ok(fired.length >= 12, `위상 ${phase} 발화 ${fired.length}회 (실측 cron은 장중 1회)`);
    // 쿨다운이 없어 격자가 곧 알림 볼륨이다. 상한도 같이 못박는다.
    assert.ok(fired.length <= 14, `위상 ${phase} 발화 ${fired.length}회 — 고장 한 건당 그만큼 도배된다`);
    for (let i = 1; i < fired.length; i++) {
      assert.ok(
        fired[i] - fired[i - 1] <= 32,
        `위상 ${phase}에 ${fired[i] - fired[i - 1]}분 공백 (${fired[i - 1]}분 → ${fired[i]}분)`
      );
    }
  }
});
