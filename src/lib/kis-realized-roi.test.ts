import { test } from 'node:test';
import assert from 'node:assert';
import { matchRealizedRoi, type ProfitEntry, type RealFill } from './kis-api.ts';

// 실거래 화면의 ROI(%)·ROI(금액)을 만드는 조인이다. 체결 내역(일별체결)에는 손익이
// 없고, 손익은 별도 TR(기간별매매손익)이 '종목_일자' 단위로만 준다. 그 둘을 붙이는
// 것이 이 함수다 — 붙이는 방식이 틀리면 화면의 손익이 조용히 틀린다.
//
// 원칙: **원가를 확보 못 한 SELL에는 값을 붙이지 않는다.** 0%가 아니라 없음이다
// (없으면 화면이 '측정 불가'로 표시한다).

const SELL = (code: string, time: string, qty: number): RealFill =>
  ({ action: 'SELL', code, time, qty: String(qty) });

const buckets = (m: Record<string, ProfitEntry[]>) => new Map(Object.entries(m));

test('BUY 행은 손질하지 않고 그대로 통과한다', () => {
  const fills: RealFill[] = [{ action: 'BUY', code: '005930', time: '2026-07-30 09:30:00', qty: '10' }];
  const [out] = matchRealizedRoi(fills, buckets({}));
  assert.equal(out.roi, undefined);
  assert.equal(out.roiAmount, undefined);
});

test('같은 종목·같은 날 버킷을 찾아 붙인다', () => {
  const out = matchRealizedRoi(
    [SELL('005930', '2026-07-30 14:00:00', 10)],
    buckets({ '005930_20260730': [{ sellQty: 10, roiPct: '3.5', roiAmount: 35_000 }] }),
  )[0];
  assert.equal(out.roiAmount, 35_000);
  assert.equal(out.roi, '+3.5');
});

test('손실은 부호가 붙는다', () => {
  const out = matchRealizedRoi(
    [SELL('005930', '2026-07-30 14:00:00', 10)],
    buckets({ '005930_20260730': [{ sellQty: 10, roiPct: '-2.0', roiAmount: -20_000 }] }),
  )[0];
  assert.equal(out.roi, '-2.0');
  assert.equal(out.roiAmount, -20_000);
});

test('원가가 부족하면 아무것도 붙이지 않는다 — 0%가 아니라 측정 불가다', () => {
  const out = matchRealizedRoi(
    [SELL('005930', '2026-07-30 14:00:00', 10)],
    buckets({ '005930_20260730': [{ sellQty: 4, roiPct: '3.0', roiAmount: 12_000 }] }),
  )[0];
  assert.equal(out.roi, undefined, '부분만 아는 손익을 전체인 양 적으면 안 된다');
  assert.equal(out.roiAmount, undefined);
});

test('버킷이 아예 없으면 붙이지 않는다 (모의투자·조회 실패 경로)', () => {
  const out = matchRealizedRoi([SELL('005930', '2026-07-30 14:00:00', 10)], buckets({}))[0];
  assert.equal(out.roiAmount, undefined);
});

test('날짜가 다르면 남의 손익을 가져오지 않는다', () => {
  const out = matchRealizedRoi(
    [SELL('005930', '2026-07-30 14:00:00', 10)],
    buckets({ '005930_20260729': [{ sellQty: 10, roiPct: '9.9', roiAmount: 99_000 }] }),
  )[0];
  assert.equal(out.roiAmount, undefined);
});

test('같은 날 두 번 팔면 버킷을 나눠 쓴다 — 두 번째가 첫 번째 손익을 재사용하지 않는다', () => {
  const outs = matchRealizedRoi(
    [SELL('005930', '2026-07-30 10:00:00', 6), SELL('005930', '2026-07-30 14:00:00', 4)],
    buckets({ '005930_20260730': [{ sellQty: 10, roiPct: '5.0', roiAmount: 50_000 }] }),
  );
  assert.equal(outs[0].roiAmount, 30_000);
  assert.equal(outs[1].roiAmount, 20_000);
  assert.equal((outs[0].roiAmount as number) + (outs[1].roiAmount as number), 50_000,
    '쪼개 붙인 합이 원래 실현손익과 같아야 한다');
});

test('버킷 여러 개를 FIFO로 소진하고 비율은 수량 가중이다', () => {
  const out = matchRealizedRoi(
    [SELL('005930', '2026-07-30 14:00:00', 10)],
    buckets({
      '005930_20260730': [
        { sellQty: 5, roiPct: '10.0', roiAmount: 50_000 },
        { sellQty: 5, roiPct: '0.0', roiAmount: 0 },
      ],
    }),
  )[0];
  assert.equal(out.roiAmount, 50_000);
  assert.equal(out.roi, '+5.0', '10%와 0%를 반씩 팔았으면 5%다');
});

test('입력 버킷을 훼손하지 않는다 — 같은 Map으로 다시 부르면 같은 답이 나온다', () => {
  const b = buckets({ '005930_20260730': [{ sellQty: 10, roiPct: '3.0', roiAmount: 30_000 }] });
  const fills = [SELL('005930', '2026-07-30 14:00:00', 10)];
  const first = matchRealizedRoi(fills, b)[0];
  const second = matchRealizedRoi(fills, b)[0];
  assert.equal(second.roiAmount, first.roiAmount);
  assert.equal(b.get('005930_20260730')![0].sellQty, 10, '호출자의 버킷이 소진돼선 안 된다');
});

test('원본 fill 객체를 in-place로 고치지 않는다', () => {
  const fills = [SELL('005930', '2026-07-30 14:00:00', 10)];
  matchRealizedRoi(fills, buckets({ '005930_20260730': [{ sellQty: 10, roiPct: '3.0', roiAmount: 30_000 }] }));
  assert.equal(fills[0].roiAmount, undefined);
});
