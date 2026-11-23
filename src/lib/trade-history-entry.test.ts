import { test } from 'node:test';
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { buildHistoryEntry, orderCarriedAPrice } from './trade-history-entry.ts';
import { buildOrderRequest } from './kis-api.ts';

// 수동 주문 기록이 체결가를 0으로 적던 버그를 막는다.
//
// 2026-07-08에 "시장가 수동 매도가 price=0으로 박힌다"를 발견하고 안 고쳤고,
// 2026-11-06에 다섯 건이 똑같이 박혔다. 0은 숫자라서 뒤에서 계산에 그대로
// 들어간다 — 손익이 "매입원가 전액 손실"로 보이거나, 아예 계산을 포기하게 된다.
//
// 매도에 지정가가 없는 건 설계다(손절·트레일링은 체결 자체가 목적). 그래서
// 매도 기록의 price는 **구조적으로** 모르는 값이고, 모르는 값은 null로 적는다.

const AT = '2026-01-07 09:30:00';

function entry(over: Partial<Parameters<typeof buildHistoryEntry>[0]> = {}) {
  return buildHistoryEntry({
    time: AT, code: '000111', side: 'sell', qty: 10,
    price: 0, ordType: 'market', isVirtual: false, origin: 'manual', ...over,
  });
}

test('시장가 매도는 price가 0이 아니라 null이다 — 모르는 값을 숫자로 적지 않는다', () => {
  const e = entry();
  assert.equal(e.price, null);
  assert.equal(e.ord_type, 'market');
  assert.equal(e.action, 'SELL');
});

test('매도는 지정가로 요청해도 시장가다 — 클라이언트가 보낸 단가를 기록에 싣지 않는다', () => {
  // kis-api의 buildOrderRequest가 매도를 항상 ORD_DVSN=01(시장가)로 보낸다.
  // 그런데 기록만 단가를 적으면 "그 가격에 팔렸다"는 거짓이 남는다.
  const e = entry({ ordType: 'limit', price: 10000 });
  assert.equal(e.price, null);
  assert.equal(e.ord_type, 'market');
});

test('지정가 매수는 실린 단가를 그대로 적는다', () => {
  const e = entry({ side: 'buy', ordType: 'limit', price: 10000 });
  assert.equal(e.price, 10000);
  assert.equal(e.ord_type, 'limit');
  assert.equal(e.action, 'BUY');
});

test('시장가 매수도 체결가를 모른다 — null이다', () => {
  const e = entry({ side: 'buy', ordType: 'market', price: 10000 });
  assert.equal(e.price, null);
  assert.equal(e.ord_type, 'market');
});

test('단가 없는 지정가 매수는 null이다 — 0을 단가로 적지 않는다', () => {
  // 이 입력은 buildOrderRequest가 예외로 거부한다. 기록도 같은 판단을 해야
  // "주문은 거부됐는데 기록엔 0원이 남는" 모양이 안 나온다.
  assert.equal(entry({ side: 'buy', ordType: 'limit', price: 0 }).price, null);
  assert.equal(entry({ side: 'buy', ordType: 'limit', price: undefined }).price, null);
});

test('가상/실전 구분과 기본 사유는 그대로 유지된다', () => {
  assert.equal(entry({ isVirtual: true }).type, 'virtual');
  assert.equal(entry().type, 'real');
  assert.equal(entry().reason, 'Manual Dashboard Trade');
  assert.equal(entry().time, AT);
  assert.equal(entry().qty, 10);
});

// ── 기록과 실제로 보낸 주문이 어긋나지 않는다 ────────────────────────
// 규칙이 두 파일에 있으면 한쪽만 바뀐다. 그 드리프트를 여기서 잡는다.

test('price가 있는 기록 ⇔ 주문에 ORD_UNPR이 실린다', () => {
  const cases: Array<{ side: 'buy' | 'sell'; ordType: 'market' | 'limit'; price: number }> = [
    { side: 'buy', ordType: 'limit', price: 10000 },
    { side: 'buy', ordType: 'market', price: 10000 },
    { side: 'sell', ordType: 'limit', price: 10000 },
    { side: 'sell', ordType: 'market', price: 0 },
  ];

  for (const c of cases) {
    const sent = buildOrderRequest('000111', 10, c.side, {
      accountNo: '1234567801', isVirtual: false,
      ordType: c.ordType, limitPrice: c.price,
    });
    const carriedPrice = sent.body.ORD_UNPR !== '0';
    assert.equal(
      orderCarriedAPrice(c.side, c.ordType, c.price), carriedPrice,
      `${c.side}/${c.ordType}: 기록은 ${orderCarriedAPrice(c.side, c.ordType, c.price)}인데 `
      + `주문 ORD_UNPR=${sent.body.ORD_UNPR}`);
  }
});

// ── 라우트가 실제로 이 함수를 쓴다 ──────────────────────────────────
// 라우트는 next/server 때문에 node --test에서 import할 수 없다. 순수 함수가
// 맞아도 호출부가 옛 코드를 그대로 두면 버그는 살아 있으므로 소스로 확인한다
// (scripts/check_heartbeat.py 배선 테스트와 같은 이유).

const ROUTE = readFileSync('src/app/api/trade/order/route.ts', 'utf8');
// 주석은 뺀다 — 고친 이유를 적어 둔 주석이 금지 패턴에 걸리면 안 된다.
const ROUTE_CODE = ROUTE.split('\n').filter(l => !l.trim().startsWith('//')).join('\n');

test('주문 라우트가 기록을 직접 조립하지 않는다', () => {
  assert.ok(ROUTE_CODE.includes('buildHistoryEntry'),
    '라우트가 buildHistoryEntry를 안 쓴다 — 기록 규칙이 두 곳에 갈린다');
  assert.ok(!/price:\s*Number\(price\)\s*\|\|\s*0/.test(ROUTE_CODE),
    '라우트에 `price: Number(price) || 0`이 남아 있다 — 시장가가 0원으로 박힌다');
});

// ── 누가 낸 주문인지 적는다 ─────────────────────────────────────────
// 프로그램도 사람도 같은 라우트를 지나는데 기록은 전부 'Manual Dashboard Trade'였다.
// 2026-11-23 정산이 세 건 막힌 원인이고, 나까지 "사용자가 반복 매매했다"고 오독했다.

test('출처를 기록에 남긴다', () => {
  assert.equal(entry({ origin: 'manual' }).origin, 'manual');
  assert.equal(entry({ origin: 'program' }).origin, 'program');
});

test('사유 기본값도 출처를 따른다 — 프로그램 주문에 Manual을 붙이지 않는다', () => {
  assert.equal(entry({ origin: 'manual' }).reason, 'Manual Dashboard Trade');
  assert.equal(entry({ origin: 'program' }).reason, 'Program Order');
  assert.equal(entry({ origin: 'program', reason: '[프로그램:sim4_bull] 손절' }).reason,
    '[프로그램:sim4_bull] 손절', '명시한 사유가 이긴다');
});

test('주문 라우트가 웹훅 인증으로 출처를 가른다', () => {
  assert.ok(/origin:\s*isAuthorizedByWebhook\s*\?\s*'program'\s*:\s*'manual'/.test(ROUTE_CODE),
    '라우트가 출처를 안 넘기면 기록이 다시 전부 manual이 된다');
});
