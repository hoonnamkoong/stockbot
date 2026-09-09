import { test } from 'node:test';
import assert from 'node:assert';
import { mapStockRow, sortRows, nextSort, parseNum } from './research-rows.ts';

// 공개 페이지와 /research가 이 코드를 함께 쓴다. 사본을 두면 스크래퍼가 포맷을
// 바꿀 때 한쪽만 고쳐지고, 다른 화면은 **빈 칸이 아니라 조용히 0**이 된다.

test('한 필드가 네 이름으로 와도 같은 자리에 들어간다', () => {
  const names = ['recent_posts_count', '게시물', '당일_게시글수', '게시글수'];
  for (const key of names) {
    const row = mapStockRow({ code: '005930', [key]: 123 });
    assert.equal(row.recent_posts_count, 123, key);
  }
});

test('현재가는 문자열로 와도 숫자가 된다', () => {
  assert.equal(mapStockRow({ 현재가: '70,000원' }).price, 70000);
  assert.equal(mapStockRow({ price: 70000 }).current_price, 70000);
});

test('키워드는 문자열로 와도 배열이 된다', () => {
  assert.deepEqual(mapStockRow({ top_keywords: '반도체, HBM' }).top_keywords,
    ['반도체', 'HBM']);
  assert.deepEqual(mapStockRow({ 키워드: ['A'] }).top_keywords, ['A']);
});

test('원본 필드는 살아남는다 — 표가 쓰는 열이 매핑 목록보다 많다', () => {
  assert.equal(mapStockRow({ code: 'X', amount: 999 }).amount, 999);
});

test('parseNum은 못 읽으면 0이다', () => {
  assert.equal(parseNum(null), 0);
  assert.equal(parseNum('n/a'), 0);
  assert.equal(parseNum('-3.5%'), -3.5);
});

// ── 정렬 ────────────────────────────────────────────────────────

const ROWS = [{ n: 3 }, { n: 1 }, { n: 2 }];

test('내림차순이 기본이고 같은 열을 다시 누르면 뒤집는다', () => {
  const a = nextSort({ key: null, direction: 'desc' }, 'n');
  assert.deepEqual(a, { key: 'n', direction: 'desc' });
  assert.deepEqual(nextSort(a, 'n'), { key: 'n', direction: 'asc' });
});

test('다른 열을 누르면 내림차순부터 시작한다', () => {
  assert.deepEqual(nextSort({ key: 'n', direction: 'asc' }, 'm'),
    { key: 'm', direction: 'desc' });
});

test('정렬이 원본 배열을 건드리지 않는다', () => {
  const sorted = sortRows(ROWS, { key: 'n', direction: 'asc' });
  assert.deepEqual(sorted.map(r => r.n), [1, 2, 3]);
  assert.deepEqual(ROWS.map(r => r.n), [3, 1, 2], '원본이 바뀌었다');
});

test('키가 없으면 그대로 돌려준다', () => {
  assert.equal(sortRows(ROWS, { key: null, direction: 'desc' }), ROWS);
});

test('쉼표와 퍼센트가 붙은 문자열도 숫자로 정렬된다', () => {
  const rows = [{ v: '1,200' }, { v: '900' }, { v: '10,000' }];
  assert.deepEqual(sortRows(rows, { key: 'v', direction: 'desc' }).map(r => r.v),
    ['10,000', '1,200', '900']);
});
