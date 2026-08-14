import { test } from 'node:test';
import assert from 'node:assert';
import { pushTurnHistory, TURN_HISTORY_MAX } from './turn-history.ts';

const turn = (id: string, pnl: number | null = 0) => ({
  id, ended_at: `2026-08-14T${id.padStart(2, '0')}:00:00`, started_at: '2026-08-01T09:00:00',
  sim: 'sim4', capital: 2_000_000, pnl, by_tag: {}, fees: 0,
});

test('가장 최근 턴이 맨 앞에 온다', () => {
  const h = pushTurnHistory([turn('1')], turn('2'));
  assert.deepEqual(h.map((t) => t.id), ['2', '1']);
});

test('이력이 없던 상태에서도 첫 턴이 들어간다', () => {
  for (const empty of [null, undefined, []]) {
    assert.equal(pushTurnHistory(empty as any, turn('1')).length, 1);
  }
});

test(`${TURN_HISTORY_MAX}개를 넘으면 가장 오래된 것이 빠진다`, () => {
  // config는 GitHub 파일이라 무한히 키울 수 없다.
  let h: any[] = [];
  for (let i = 1; i <= TURN_HISTORY_MAX + 1; i++) h = pushTurnHistory(h, turn(String(i)));

  assert.equal(h.length, TURN_HISTORY_MAX);
  assert.equal(h[0].id, String(TURN_HISTORY_MAX + 1), '최신이 앞');
  assert.ok(!h.some((t) => t.id === '1'), '가장 오래된 것이 빠져야 한다');
});

test('측정 불가 턴도 그대로 남는다 — 실패를 지우면 실패한 적이 없어 보인다', () => {
  const h = pushTurnHistory([], turn('1', null));
  assert.equal(h[0].pnl, null);
});
