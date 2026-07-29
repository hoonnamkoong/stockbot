import { test } from 'node:test';
import assert from 'node:assert';
import { authorizeManualOrder, validateArmRequest } from './trade-auth.ts';
import { kstTimestamp } from './kst.ts';

// 실거래 문을 여는 판정이다. 라우트 안에 있을 때는 테스트가 닿지 않아,
// 이 경로의 결함은 전부 사용자가 눈으로 발견했다.

const BASE = {
  authHeader: null,
  webhookSecret: 'hook-secret',
  hasSession: true,
  pin: '1234',
  tradePin: '1234',
};

test('세션 + 맞는 PIN이면 통과', () => {
  assert.deepEqual(authorizeManualOrder(BASE), { ok: true });
});

test('세션이 없으면 401 — PIN만으로는 절대 통과하지 않는다', () => {
  const v = authorizeManualOrder({ ...BASE, hasSession: false });
  assert.equal(v.ok, false);
  assert.equal((v as any).status, 401);
});

test('PIN이 틀리면 403', () => {
  const v = authorizeManualOrder({ ...BASE, pin: '9999' });
  assert.equal((v as any).status, 403);
});

test('PIN이 비어 있거나 타입이 달라도 통과하지 않는다', () => {
  for (const pin of [undefined, null, '', 0, 1234, ' 1234', {}]) {
    const v = authorizeManualOrder({ ...BASE, pin });
    assert.equal(v.ok, false, `pin=${JSON.stringify(pin)} 이 통과했다`);
  }
});

test('서버에 TRADE_PIN이 없으면 통과가 아니라 500이다', () => {
  // 폴백 PIN을 두면 그 폴백이 곧 실거래 비밀번호가 된다.
  const v = authorizeManualOrder({ ...BASE, tradePin: undefined, pin: undefined });
  assert.equal((v as any).status, 500);
});

test('세션 없음과 PIN 틀림은 같은 문구를 준다 — 어느 쪽이 틀렸는지 알려주지 않는다', () => {
  const noSession = authorizeManualOrder({ ...BASE, hasSession: false }) as any;
  const badPin = authorizeManualOrder({ ...BASE, pin: '9999' }) as any;
  assert.equal(noSession.error, badPin.error);
});

test('웹훅 시크릿이 맞으면 세션·PIN 없이 통과한다 (자동화 엔진 경로)', () => {
  const v = authorizeManualOrder({
    ...BASE, authHeader: 'Bearer hook-secret', hasSession: false, pin: undefined,
  });
  assert.deepEqual(v, { ok: true });
});

test('서버에 웹훅 시크릿이 없으면 어떤 헤더도 통과시키지 않는다', () => {
  // webhookSecret이 빈 문자열/undefined일 때 `Bearer undefined` 같은 헤더가
  // 우연히 맞아떨어지면 인증 없는 주문 경로가 열린다.
  for (const secret of [undefined, '']) {
    for (const header of ['Bearer undefined', 'Bearer ', 'Bearer null', null]) {
      const v = authorizeManualOrder({
        ...BASE, webhookSecret: secret, authHeader: header, hasSession: false,
      });
      assert.equal(v.ok, false, `secret=${secret} header=${header} 가 통과했다`);
    }
  }
});

test('웹훅 헤더가 조금이라도 다르면 통과하지 않는다', () => {
  for (const header of ['bearer hook-secret', 'Bearer hook-secret ', 'hook-secret', 'Bearer HOOK-SECRET']) {
    const v = authorizeManualOrder({ ...BASE, authHeader: header, hasSession: false });
    assert.equal(v.ok, false, `${header} 가 통과했다`);
  }
});

// ── 프로그램 매매 ON 판정 ───────────────────────────────────────────

const IDS = ['sim1_psych', 'sim4_bull'];

test('화이트리스트에 있는 심 + 예산이면 켜진다', () => {
  assert.deepEqual(
    validateArmRequest({ selectedSim: 'sim1_psych', budget: 1_000_000, tradeableIds: IDS }),
    { ok: true, sim: 'sim1_psych', budget: 1_000_000 },
  );
});

test('화이트리스트에 없는 id로는 켜지지 않는다', () => {
  for (const sim of ['sim0_libero', 'sim9_gapfade', '', null, undefined, 42, { id: 'sim1_psych' }]) {
    const v = validateArmRequest({ selectedSim: sim, budget: 1_000_000, tradeableIds: IDS });
    assert.equal(v.ok, false, `${JSON.stringify(sim)} 이 통과했다`);
  }
});

test('예산이 0 이하거나 숫자가 아니면 켜지지 않는다 (fail-closed)', () => {
  for (const budget of [0, -1, '', null, undefined, NaN, 'abc', 0.4]) {
    const v = validateArmRequest({ selectedSim: 'sim1_psych', budget, tradeableIds: IDS });
    assert.equal(v.ok, false, `budget=${JSON.stringify(budget)} 이 통과했다`);
  }
});

test('예산은 내림한 정수로 정규화된다', () => {
  const v = validateArmRequest({ selectedSim: 'sim1_psych', budget: '1000000.9', tradeableIds: IDS });
  assert.deepEqual(v, { ok: true, sim: 'sim1_psych', budget: 1_000_000 });
});

test('심이 없으면 예산 얘기를 하지 않는다 — 먼저 걸린 이유를 말한다', () => {
  const v = validateArmRequest({ selectedSim: null, budget: 0, tradeableIds: IDS }) as any;
  assert.match(v.error, /매매 심/);
});

test('빈 화이트리스트로는 아무것도 켤 수 없다', () => {
  // 목록 조회가 실패해 빈 배열이 오던 시절, 사용자가 심을 골라도 선택이 조용히 버려졌다.
  // 이제 목록은 생성된 상수라 비지 않지만, 비면 켜지지 않는 것이 맞는 방향이다.
  const v = validateArmRequest({ selectedSim: 'sim1_psych', budget: 1_000_000, tradeableIds: [] });
  assert.equal(v.ok, false);
});

// ── 기록에 찍히는 시각 ──────────────────────────────────────────────

test('KST 타임스탬프는 UTC+9 고정에 초 단위까지', () => {
  // 2026-07-30 00:00:00 UTC → 같은 날 09:00:00 KST
  assert.equal(kstTimestamp(Date.UTC(2026, 6, 30, 0, 0, 0)), '2026-07-30 09:00:00');
});

test('자정을 넘어가는 경계에서 날짜가 함께 넘어간다', () => {
  assert.equal(kstTimestamp(Date.UTC(2026, 6, 30, 15, 30, 0)), '2026-07-31 00:30:00');
});

test('밀리초·T·Z가 남지 않는다 — 파이썬 기록과 같은 표기여야 붙는다', () => {
  assert.match(kstTimestamp(Date.UTC(2026, 6, 30, 4, 5, 6, 789)), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);
});
