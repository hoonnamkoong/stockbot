import { test } from 'node:test';
import assert from 'node:assert';
import {
    checkPinRateLimit,
    recordPinFailure,
    clearPinFailures,
    PIN_MAX_ATTEMPTS,
} from './pin-lockout.ts';

// 이 잠금은 **4자리 TRADE_PIN에 대한 유일한 무차별 대입 방어**다. 여기가 fail-open이면
// 10,000개를 다 시도하는 데 아무 저항이 없다.
//
// 지금까지 테스트가 0개였던 이유는 방어가 사소해서가 아니라, 21행 import가 확장자 없는
// `'./login-auth'`라 `node --test`가 모듈을 **열지도 못했기** 때문이다. 테스트가 없는 게
// 아니라 테스트를 쓸 수 없었다. 그래서 세 개의 결함(401에도 기본값 반환, catch에서
// allowed:true, PUT 응답 미검사)이 전부 조용히 살아 있었다.
//
// 실제 GitHub은 절대 부르지 않는다 — 전역 fetch를 갈아끼운다.

type Lock = { fails: number; locked_until: string | null };

const b64 = (s: string) => Buffer.from(s, 'utf-8').toString('base64');
const decode = (s: string) => JSON.parse(Buffer.from(s, 'base64').toString('utf-8')) as Lock;

/** GitHub Contents API의 GET 200 응답 모양 */
function getOk(lock: Lock, sha: string) {
    return { ok: true, status: 200, json: async () => ({ sha, content: b64(JSON.stringify(lock)) }) };
}
const fail = (status: number) => ({ ok: false, status, text: async () => `HTTP ${status}` });

/** 전역 fetch를 스텁으로 갈아끼우고 끝나면 되돌린다. */
async function withFetch<T>(impl: any, fn: () => Promise<T>): Promise<T> {
    const original = globalThis.fetch;
    process.env.GITHUB_PAT = 'test-pat';
    (globalThis as any).fetch = impl;
    try {
        return await fn();
    } finally {
        (globalThis as any).fetch = original;
    }
}

/** 응답을 순서대로 내주는 스텁. 호출 로그를 같이 남긴다. */
function scripted(responses: any[]) {
    const calls: { method: string; body?: any }[] = [];
    let i = 0;
    const impl = async (_url: string, init?: any) => {
        calls.push({ method: init?.method ?? 'GET', body: init?.body });
        const r = responses[i++];
        if (!r) throw new Error(`스텁에 없는 ${i}번째 호출`);
        if (typeof r === 'function') return r();
        return r;
    };
    return { impl, calls };
}

/** sha를 실제로 검사하는 GitHub 모사 — 낡은 sha로 PUT하면 409. */
function githubStore(initial: Lock = { fails: 0, locked_until: null }) {
    const state = { lock: initial, sha: 'sha-0' };
    const counts = { get: 0, put: 0, conflict: 0 };
    let seq = 0;
    const impl = async (_url: string, init?: any) => {
        const method = init?.method ?? 'GET';
        if (method === 'GET') {
            counts.get++;
            return getOk(state.lock, state.sha);
        }
        counts.put++;
        const body = JSON.parse(init.body);
        if (body.sha !== state.sha) {
            counts.conflict++;
            return fail(409);
        }
        state.lock = decode(body.content);
        state.sha = `sha-${++seq}`;
        return { ok: true, status: 200, json: async () => ({ content: { sha: state.sha } }) };
    };
    return { state, counts, impl };
}

const future = new Date(Date.now() + 7 * 60000).toISOString();
const past = new Date(Date.now() - 60000).toISOString();

// ── 조회 판정 ────────────────────────────────────────────────────────────────

test('200 + 미래 locked_until → 차단하고 남은 분을 돌려준다', async () => {
    const { impl } = scripted([getOk({ fails: 0, locked_until: future }, 'sha-0')]);
    const v = await withFetch(impl, () => checkPinRateLimit());
    assert.equal(v.allowed, false);
    assert.ok(v.retryAfterMin > 0 && v.retryAfterMin <= 7, `남은 분이 이상하다: ${v.retryAfterMin}`);
});

test('200 + fails:0 → 통과', async () => {
    const { impl } = scripted([getOk({ fails: 0, locked_until: null }, 'sha-0')]);
    assert.deepEqual(await withFetch(impl, () => checkPinRateLimit()), { allowed: true, retryAfterMin: 0 });
});

test('지난 locked_until은 만료다 → 통과', async () => {
    const { impl } = scripted([getOk({ fails: 2, locked_until: past }, 'sha-0')]);
    assert.equal((await withFetch(impl, () => checkPinRateLimit())).allowed, true);
});

test('401(PAT 만료) → 차단한다 — 잠금이 통째로 사라지면 안 된다', async () => {
    // 이게 제일 위험한 경로다. PAT가 만료되면 잠금 상태를 읽을 수 없는데,
    // 예전 코드는 그걸 "잠금 없음"과 구분하지 못했다.
    const { impl } = scripted([fail(401)]);
    const v = await withFetch(impl, () => checkPinRateLimit());
    assert.equal(v.allowed, false);
    assert.ok(v.retryAfterMin > 0, '차단이면 재시도 시간을 줘야 한다');
});

test('500(깃허브 장애) → 차단한다', async () => {
    const { impl } = scripted([fail(500)]);
    assert.equal((await withFetch(impl, () => checkPinRateLimit())).allowed, false);
});

test('네트워크 예외 → 차단한다', async () => {
    const impl = async () => { throw new Error('ECONNRESET'); };
    const v = await withFetch(impl, () => checkPinRateLimit());
    assert.equal(v.allowed, false);
    assert.ok(v.retryAfterMin > 0);
});

test('본문이 깨져 있어도 차단한다', async () => {
    const { impl } = scripted([{ ok: true, status: 200, json: async () => ({ sha: 's', content: b64('{not json') }) }]);
    assert.equal((await withFetch(impl, () => checkPinRateLimit())).allowed, false);
});

test('404(파일 없음) → 통과 — 최초 실행이지 장애가 아니다', async () => {
    const { impl } = scripted([fail(404)]);
    assert.deepEqual(await withFetch(impl, () => checkPinRateLimit()), { allowed: true, retryAfterMin: 0 });
});

// ── 기록 ────────────────────────────────────────────────────────────────────

test('409 한 번 뒤 성공하면 최종적으로 기록된다', async () => {
    const { impl, calls } = scripted([
        getOk({ fails: 0, locked_until: null }, 'sha-0'),  // GET
        fail(409),                                          // PUT (sha 충돌)
        getOk({ fails: 1, locked_until: null }, 'sha-1'),  // 다시 읽기
        { ok: true, status: 200, json: async () => ({}) },  // PUT 성공
    ]);
    const r = await withFetch(impl, () => recordPinFailure());
    assert.equal(r.recorded, true, '재시도했으면 기록됐다고 말해야 한다');
    assert.equal(calls.length, 4, '충돌 뒤 다시 읽고 PUT해야 한다');
    assert.equal(decode(JSON.parse(calls[3].body).content).fails, 2, '재시도는 다시 읽은 값 위에 쌓는다');
});

test('PUT이 끝내 실패하면 삼키지 않고 알린다 — 단 예외로 주문 경로를 죽이지 않는다', async () => {
    const { impl } = scripted([
        getOk({ fails: 0, locked_until: null }, 'sha-0'), fail(409),
        getOk({ fails: 0, locked_until: null }, 'sha-1'), fail(409),
        getOk({ fails: 0, locked_until: null }, 'sha-2'), fail(409),
    ]);
    const r = await withFetch(impl, () => recordPinFailure());
    assert.equal(r.recorded, false);
    assert.ok(r.error, '무엇이 실패했는지 남아야 한다');
});

test('조회가 401이면 기록도 실패로 보고한다', async () => {
    const { impl } = scripted([fail(401)]);
    const r = await withFetch(impl, () => recordPinFailure());
    assert.equal(r.recorded, false);
});

test('404면 파일을 새로 만들어 첫 실패를 기록한다', async () => {
    const { impl, calls } = scripted([fail(404), { ok: true, status: 201, json: async () => ({}) }]);
    const r = await withFetch(impl, () => recordPinFailure());
    assert.equal(r.recorded, true);
    const body = JSON.parse(calls[1].body);
    assert.equal(body.sha, undefined, '새 파일이면 sha를 보내지 않는다');
    assert.equal(decode(body.content).fails, 1);
});

test('임계에 닿으면 잠근다', async () => {
    const store = githubStore({ fails: PIN_MAX_ATTEMPTS - 1, locked_until: null });
    const r = await withFetch(store.impl, () => recordPinFailure());
    assert.equal(r.recorded, true);
    assert.ok(store.state.lock.locked_until, `${PIN_MAX_ATTEMPTS}번째 실패는 잠가야 한다`);
});

test('동시 실패 기록이 sha 충돌에도 누락 없이 집계된다', async () => {
    // 예전 코드는 PUT 응답을 안 봤다 — 20건이 동시에 오면 1건만 반영되고
    // 19건이 조용히 사라져 fails:1이 됐다. 무차별 대입이 병렬이면 무력화됐다.
    const store = githubStore({ fails: 0, locked_until: null });
    const results = await withFetch(store.impl, () =>
        Promise.all([recordPinFailure(), recordPinFailure(), recordPinFailure()]));
    assert.deepEqual(results.map((r) => r.recorded), [true, true, true]);
    assert.ok(store.counts.conflict > 0, '이 테스트가 실제로 충돌을 만들었는지 확인');
    assert.equal(store.state.lock.fails, 3, '세 번의 실패가 모두 세어져야 한다');
});

// ── 해제 ────────────────────────────────────────────────────────────────────

test('성공하면 카운터를 지운다', async () => {
    const store = githubStore({ fails: 3, locked_until: null });
    const r = await withFetch(store.impl, () => clearPinFailures());
    assert.equal(r.cleared, true);
    assert.deepEqual(store.state.lock, { fails: 0, locked_until: null });
});

test('지울 게 없으면 PUT하지 않는다', async () => {
    const store = githubStore({ fails: 0, locked_until: null });
    await withFetch(store.impl, () => clearPinFailures());
    assert.equal(store.counts.put, 0);
});

test('해제 실패는 잠금을 남긴다 — 안전한 방향이지만 보고는 한다', async () => {
    const { impl } = scripted([fail(500)]);
    const r = await withFetch(impl, () => clearPinFailures());
    assert.equal(r.cleared, false);
    assert.ok(r.error);
});
