import { test } from 'node:test';
import assert from 'node:assert';
import { regime6Label, REGIME6_ORDER } from './regime6.ts';

test('6단계 값은 한글 라벨로 보인다', () => {
  assert.deepEqual(REGIME6_ORDER.map(regime6Label),
    ['매우하락', '하락', '약한횡보', '강한횡보', '상승', '매우상승']);
});

test('모르는 값·없음은 null — 횡보 같은 기본값으로 채우지 않는다', () => {
  assert.equal(regime6Label(null), null);
  assert.equal(regime6Label(undefined), null);
  assert.equal(regime6Label('SIDEWAYS'), null);
  assert.equal(regime6Label('BANANA'), null);
});
