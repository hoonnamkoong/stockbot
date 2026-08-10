import { test } from 'node:test';
import assert from 'node:assert';
import { buildOrderRequest } from './kis-api.ts';

// 실제 돈이 나가는 주문의 파라미터 조립이다. axios 호출 직전까지가 전부 순수 계산인데
// 테스트가 없었고, 실제로 그 순수한 부분에서 버그가 났다 —
// 시장가 매도에 단가를 실어 보내 KIS가 거부한 건(683cc55).
//
// 여기서 보는 것은 네 갈래(매수/매도 × 실전/모의)와 계좌번호 분해, 그리고 시장가 규칙이다.

const REAL = { accountNo: '1234567801', isVirtual: false };
const VIRTUAL = { accountNo: '1234567801', isVirtual: true };

test('tr_id는 매수/매도 × 실전/모의 네 갈래', () => {
  assert.equal(buildOrderRequest('005930', 1, 'buy', REAL).trId, 'TTTC0802U');
  assert.equal(buildOrderRequest('005930', 1, 'sell', REAL).trId, 'TTTC0801U');
  assert.equal(buildOrderRequest('005930', 1, 'buy', VIRTUAL).trId, 'VTTC0802U');
  assert.equal(buildOrderRequest('005930', 1, 'sell', VIRTUAL).trId, 'VTTC0801U');
});

test('실전과 모의를 헷갈리면 안 된다 — 접두사만 다르고 뒤 8자리는 같다', () => {
  // T/V 한 글자 차이라 조건을 뒤집어도 형태가 그럴듯하다. 실전에 V를 보내면
  // 주문이 조용히 모의 서버로 가고, 반대는 진짜 돈이 나간다.
  for (const side of ['buy', 'sell'] as const) {
    const real = buildOrderRequest('005930', 1, side, REAL).trId;
    const virt = buildOrderRequest('005930', 1, side, VIRTUAL).trId;
    assert.ok(real.startsWith('T'), `실전은 T로 시작해야 한다: ${real}`);
    assert.ok(virt.startsWith('V'), `모의는 V로 시작해야 한다: ${virt}`);
    assert.equal(real.slice(1), virt.slice(1));
  }
});

test('시장가 주문의 단가는 항상 "0" — 값을 실으면 KIS가 거부한다', () => {
  // 683cc55 회귀 방지. 매수·매도 양쪽 모두 해당한다.
  for (const side of ['buy', 'sell'] as const) {
    const { body } = buildOrderRequest('005930', 10, side, REAL);
    assert.equal(body.ORD_UNPR, '0', `${side}의 ORD_UNPR가 0이 아니다`);
    assert.equal(body.ORD_DVSN, '01', '01=시장가');
  }
});

test('계좌번호가 CANO 8자리 + 상품코드 2자리로 갈린다', () => {
  const { body } = buildOrderRequest('005930', 1, 'buy', REAL);
  assert.equal(body.CANO, '12345678');
  assert.equal(body.ACNT_PRDT_CD, '01');
});

test('상품코드가 없는 계좌번호는 "01"로 채운다', () => {
  const { body } = buildOrderRequest('005930', 1, 'buy', { accountNo: '12345678', isVirtual: false });
  assert.equal(body.CANO, '12345678');
  assert.equal(body.ACNT_PRDT_CD, '01');
});

test('종목코드와 수량이 문자열로 실린다', () => {
  const { body } = buildOrderRequest('000660', 7, 'sell', REAL);
  assert.equal(body.PDNO, '000660');
  assert.equal(body.ORD_QTY, '7');
  assert.equal(typeof body.ORD_QTY, 'string', 'KIS는 숫자형을 받지 않는다');
});

test('지정가 매수는 ORD_DVSN=00과 실제 단가를 싣는다', () => {
  const { body } = buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit', limitPrice: 111000 });

  assert.equal(body.ORD_DVSN, '00', '00=지정가');
  assert.equal(body.ORD_UNPR, '111000');
});

test('ordType을 안 주면 기존 시장가 그대로다 — 호출부를 안 고쳐도 동작이 안 바뀐다', () => {
  const { body } = buildOrderRequest('005930', 1, 'buy', REAL);

  assert.equal(body.ORD_DVSN, '01');
  assert.equal(body.ORD_UNPR, '0');
});

test('지정가인데 단가가 없거나 0이면 시장가로 떨어지지 않는다 — 던진다', () => {
  // 조용히 시장가로 내면 "원하는 가격에만 산다"가 소리 없이 깨진다.
  assert.throws(() => buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit' }));
  assert.throws(() => buildOrderRequest('353200', 3, 'buy',
    { ...REAL, ordType: 'limit', limitPrice: 0 }));
});

test('매도는 지정가를 요청해도 시장가다 — 손절은 체결 자체가 목적이다', () => {
  const { body } = buildOrderRequest('353200', 3, 'sell',
    { ...REAL, ordType: 'limit', limitPrice: 111000 });

  assert.equal(body.ORD_DVSN, '01');
  assert.equal(body.ORD_UNPR, '0');
});
