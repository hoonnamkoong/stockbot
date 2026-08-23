import { test } from 'node:test';
import assert from 'node:assert';
import { formatMoney } from './currency-format.ts';

test('KRW는 반올림 정수 + 원', () => {
  assert.equal(formatMoney(1234567.8, 'KRW'), '1,234,568원');
});

test('USD는 소수점 2자리 + $ 접두', () => {
  assert.equal(formatMoney(45.6, 'USD'), '$45.60');
  assert.equal(formatMoney(12345.678, 'USD'), '$12,345.68');
});

test('음수도 부호를 보존한다', () => {
  assert.equal(formatMoney(-45.6, 'USD'), '-$45.60');
  assert.equal(formatMoney(-1000, 'KRW'), '-1,000원');
});
