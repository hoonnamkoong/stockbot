import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { brokerRejection, classifyOrderFailure } from './order-error.ts';

// 이 판정이 틀리면 **시스템 고장이 "시장이 거부했다"로 기록된다.** 파이썬 호출부가
// `rejected`를 보고 경고만 찍고 넘어가기 때문이다. 돈 경로에서 제일 비싼 거짓말이라
// 판정을 라우트 밖으로 뺐다(라우트는 next/server 때문에 여기서 import를 못 한다).

test('증권사 거절은 200 + rejected', () => {
    const v = classifyOrderFailure(brokerRejection('장 종료 후에는 주문할 수 없습니다'));
    assert.deepEqual(v, { rejected: true, status: 200 });
});

test('표시 없는 예외는 전부 시스템 고장이다', () => {
    // fail-closed 방향: 모르는 것은 고장이다. 반대로 하면 새 실패 유형이 생길
    // 때마다 조용히 삼켜진다 — 이 모듈이 생긴 사고가 정확히 그 형태였다.
    for (const e of [new Error('socket hang up'),
                     new TypeError('x is not a function'),
                     { message: 'axios timeout' },
                     null,
                     undefined]) {
        assert.deepEqual(classifyOrderFailure(e), { rejected: false, status: 502 },
            `${String(e)}가 거부로 분류됐다`);
    }
});

test('거절 표시는 메시지를 그대로 지닌다', () => {
    // 대시보드가 보여주는 것이 이 문자열이다.
    assert.equal(brokerRejection('가상 예수금이 부족합니다.').message, '가상 예수금이 부족합니다.');
});

test('참 같은 값이 아니라 true만 거부다', () => {
    const e: any = new Error('x');
    e.brokerRejected = 'yes';
    assert.equal(classifyOrderFailure(e).rejected, false,
        '문자열이 거부로 통과하면 우연한 필드가 고장을 숨긴다');
});

// ── 배선 가드 ───────────────────────────────────────────────────────
// 판정을 테스트해 봐야 라우트가 안 쓰면 소용없다. 라우트는 import가 안 되므로
// 소스를 읽는다(레포 관용구).

const read = (p: string) => fs.readFileSync(path.join(process.cwd(), p), 'utf-8');

test('주문 라우트가 rejected를 하드코딩하지 않는다', () => {
    const body = read('src/app/api/trade/order/route.ts');
    assert.ok(body.includes('classifyOrderFailure(error)'),
        '주문 라우트가 실패를 분류하지 않는다 — 고장이 시장 사유로 기록된다');
    assert.ok(!body.includes('rejected: true'),
        'rejected를 하드코딩하면 분류가 무의미해진다');
});

test('KIS 주문은 rt_cd 거절만 거부로 표시한다', () => {
    const body = read('src/lib/kis-api.ts');
    assert.ok(body.includes('throw brokerRejection(res.data.msg1'),
        'rt_cd != 0을 거부로 표시하지 않는다 — 진짜 거절이 고장으로 분류된다');
    assert.ok(body.includes('brokerRejected ? e : new Error(msg)'),
        'catch가 재포장하면서 거부 표시를 버린다');
});
