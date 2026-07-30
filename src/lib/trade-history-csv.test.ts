import { test } from 'node:test';
import assert from 'node:assert';
import { parseCsvLine, parseSimHistoryCsv } from './trade-history-csv.ts';

// ── 파서 ────────────────────────────────────────────────────────────

test('따옴표 안의 콤마는 필드 구분자가 아니다', () => {
  // 실버그였다: split(',')이 사유를 첫 콤마에서 잘랐다.
  const cols = parseCsvLine('2026-07-24 09:14:58,SK이터닉스(475150),SELL,77300,5,386500,"[레인지] 트레일링 청산 (고점대비 -2%, +38.3%)"');
  assert.equal(cols.length, 7);
  assert.equal(cols[6], '[레인지] 트레일링 청산 (고점대비 -2%, +38.3%)');
});

test('따옴표 안의 따옴표는 ""로 이스케이프된다', () => {
  assert.deepEqual(parseCsvLine('a,"b ""c"" d",e'), ['a', 'b "c" d', 'e']);
});

test('빈 필드와 마지막 빈 필드를 잃지 않는다', () => {
  assert.deepEqual(parseCsvLine('a,,c,'), ['a', '', 'c', '']);
});

// ── 매핑 ────────────────────────────────────────────────────────────

const NEW_CSV = [
  'timestamp,symbol,action,price,quantity,total_amount,reason,roi,roi_amount',
  '2026-07-30 09:15:22,한진칼(180640),SELL,115700,1,115700,"[레인지] 트레일링 청산 (고점대비 -2%, +3.9%)",+3.93,4366',
  '2026-07-30 09:26:46,LG생활건강(051900),buy,303000,1,303000,"[단타] 탑승 (ADX 100.0, 기관+50,000)",,',
].join('\n');

test('신 포맷은 ROI 두 값을 붙여준다', () => {
  const [sell, buy] = parseSimHistoryCsv(NEW_CSV, 'sim10_orchestrator');
  assert.equal(sell.action, 'SELL');
  assert.equal(sell.roi, '+3.93');
  assert.equal(sell.roiAmount, 4366);
  assert.equal(sell.type, 'sim10_orchestrator');
  // 사유 안의 콤마가 ROI 열을 밀지 않는다 — 열 위치가 아니라 헤더 이름으로 찾는다.
  assert.equal(buy.reason, '[단타] 탑승 (ADX 100.0, 기관+50,000)');
});

test('매수 행의 빈 ROI는 0이 아니라 null이다', () => {
  const [, buy] = parseSimHistoryCsv(NEW_CSV, 'x');
  assert.equal(buy.roi, null);
  assert.equal(buy.roiAmount, null);
  assert.equal(buy.action, 'BUY', '소문자 action도 대문자로 맞춘다');
});

test('실현손익 0원은 값이다 — null로 뭉개지 않는다', () => {
  const csv = 'timestamp,symbol,action,price,quantity,total_amount,reason,roi,roi_amount\n'
            + 't,A(1),SELL,100,1,100,r,+0.00,0';
  const [row] = parseSimHistoryCsv(csv, 'x');
  assert.equal(row.roiAmount, 0);
  assert.equal(row.roi, '+0.00');
});

test('ROI 열이 있는 파일은 roiTracked가 참이다', () => {
  assert.equal(parseSimHistoryCsv(NEW_CSV, 'x')[0].roiTracked, true);
});

test('ROI 열이 없는 구 포맷도 그대로 읽힌다 — 그 두 값만 null이다', () => {
  const old = [
    'timestamp,symbol,action,price,quantity,total_amount,reason',
    '2026-07-24 11:46:58,HD현대마린엔진(071970),SELL,67700,5,338500,[Sim10-BEAR] 국면전환 잔여 청산',
  ].join('\n');
  const [row] = parseSimHistoryCsv(old, 'x');
  assert.equal(row.symbol, 'HD현대마린엔진(071970)');
  assert.equal(row.reason, '[Sim10-BEAR] 국면전환 잔여 청산');
  assert.equal(row.roi, null, '기록 이전이라 모르는 것이지 0%가 아니다');
  assert.equal(row.roiAmount, null);
  assert.equal(row.roiTracked, false, '실패가 아니라 기록 이전 — 화면이 경고로 도배되지 않게 구분한다');
});

test('BOM(utf-8-sig)이 붙어도 timestamp를 찾는다', () => {
  const csv = '﻿timestamp,symbol,action,price,quantity,total_amount,reason\nt1,A(1),BUY,10,1,10,r';
  const [row] = parseSimHistoryCsv(csv, 'x');
  assert.equal(row.time, 't1', 'BOM을 안 떼면 헤더 이름이 안 맞아 시각이 통째로 빈다');
});

test('total_amount가 비면 체결가×수량으로 채운다', () => {
  const csv = 'timestamp,symbol,action,price,quantity,total_amount,reason\nt,A(1),BUY,1000,3,,r';
  assert.equal(parseSimHistoryCsv(csv, 'x')[0].amount, '3,000');
});

test('헤더만 있거나 빈 파일은 빈 배열이다', () => {
  assert.deepEqual(parseSimHistoryCsv('timestamp,symbol', 'x'), []);
  assert.deepEqual(parseSimHistoryCsv('', 'x'), []);
});
