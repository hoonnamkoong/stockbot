import { test } from 'node:test';
import assert from 'node:assert';
import { parseExpiry, isTokenValid } from './kis-api.ts';

// KIS 토큰 캐시는 **파이썬이 쓰고 TS가 읽는 언어 간 계약**인데, 스키마도
// 테스트도 없었다. 이건 docs/ARCHITECTURE_DEBT.md 2-A절이 말하는 형태 그대로다
// — 같은 지식이 양쪽에 각각 인코딩돼 있고, 한쪽만 바뀌면 조용히 어긋난다.
//
// 여기가 틀리면 비용이 크다. KIS는 **1일 1회 발급 제한**이 있어서, 판정이
// 한쪽으로 치우치면 그날 매매가 통째로 잠긴다.
//   - 너무 오래 유효로 보면 → 만료된 토큰으로 모든 호출이 401
//   - 너무 빨리 만료로 보면 → 매 런이 재발급 → 제한에 걸려 잠김
//
// 생산자 형식(2026-09-01 실측): src/trade/auth.py:146-150
//   issued_at  "2026-08-31T23:12:47.004544+09:00"
//   expires_at "2026-09-01T23:12:47.004544+09:00"

const ISO_KST = '2026-09-01T23:12:47.004544+09:00';

test('생산자가 지금 쓰는 형식을 정확히 읽는다', () => {
    // 이 값이 바뀌면 파이썬 쪽(auth.py)이 형식을 바꿨다는 뜻이다.
    assert.equal(parseExpiry(ISO_KST), Date.parse('2026-09-01T14:12:47.004Z'));
});

test('오프셋 없는 문자열은 KST로 읽는다 — 파이썬과 같은 규칙', () => {
    // 파이썬은 naive 값을 KST로 간주하도록 **명시적으로 방어**한다
    // (auth.py:30-31). TS는 `new Date(v)`라 실행 환경의 로컬 시간으로 읽었고,
    // Vercel은 UTC다 — 같은 문자열을 9시간 다르게 해석했다는 뜻이다.
    const expected = Date.parse('2026-09-01T23:12:47+09:00');
    assert.equal(parseExpiry('2026-09-01T23:12:47'), expected);
    assert.equal(parseExpiry('2026-09-01 23:12:47'), expected, '공백 구분자도 같아야 한다');
    assert.equal(parseExpiry('2026-09-01T23:12'), Date.parse('2026-09-01T23:12+09:00'));
});

test('명시된 오프셋은 그대로 존중한다', () => {
    // naive 보정이 오프셋 있는 값까지 건드리면 반대 방향으로 9시간 틀어진다.
    assert.equal(parseExpiry('2026-09-01T23:12:47Z'), Date.parse('2026-09-01T23:12:47Z'));
    assert.equal(parseExpiry('2026-09-01T23:12:47+00:00'), Date.parse('2026-09-01T23:12:47Z'));
});

test('epoch 초와 밀리초를 구분한다', () => {
    // 초를 그대로 쓰면 Date.now()와 1000배 어긋나 **언제나 만료**로 읽힌다.
    // 그러면 매 런이 재발급을 시도하고 KIS 1일 1회 제한에 걸린다.
    const ms = 1788000000000;
    assert.equal(parseExpiry(ms), ms);
    assert.equal(parseExpiry(ms / 1000), ms, 'epoch 초가 들어와도 같은 시각이어야 한다');
});

test('읽을 수 없는 값은 0이다 — 0은 "모른다"가 아니라 "만료"다', () => {
    // 여기서 fail-open(유효로 간주)하면 죽은 토큰으로 주문을 시도하게 된다.
    // 만료 쪽으로 넘어져야 재발급 경로를 탄다.
    assert.equal(parseExpiry(null), 0);
    assert.equal(parseExpiry(undefined), 0);
    assert.equal(parseExpiry({}), 0);
    assert.ok(Number.isNaN(parseExpiry('쓰레기')) || parseExpiry('쓰레기') === 0);
});

test('토큰이 없으면 무조건 무효다', () => {
    assert.equal(isTokenValid(null), false);
    assert.equal(isTokenValid({}), false);
    assert.equal(isTokenValid({ expires_at: ISO_KST }), false, 'access_token이 없다');
});

test('만료 1시간 전까지만 유효로 본다', () => {
    const now = Date.now();
    const at = (ms: number) => new Date(now + ms).toISOString();
    assert.equal(isTokenValid({ access_token: 'x', expires_at: at(7200_000) }), true,
        '2시간 남았으면 유효');
    assert.equal(isTokenValid({ access_token: 'x', expires_at: at(1800_000) }), false,
        '30분 남았으면 만료 임박 — 갱신 쪽으로 넘어져야 한다');
});

test('오늘 발급한 이력이 있으면 만료돼도 유효로 본다 — 의도된 정책이다', () => {
    // KIS 1일 1회 제한 대응(V8.9.9.5). 만료된 토큰을 쓰게 되지만, 재발급이
    // 막혀 있는 상황에서는 그게 유일한 선택지다. **의도를 테스트로 못박아
    // 두지 않으면 다음 사람이 "만료됐는데 왜 유효?"로 보고 지운다.**
    const yesterday = new Date(Date.now() - 86400_000).toISOString();
    assert.equal(
        isTokenValid({ access_token: 'x', expires_at: yesterday, issued_at: new Date().toISOString() }),
        true, '오늘 발급했으면 유효');
    assert.equal(
        isTokenValid({ access_token: 'x', expires_at: yesterday, issued_at: yesterday }),
        false, '어제 발급 + 만료 = 무효');
});
