import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { isOpen } from './route-access.ts';

/**
 * 공개면은 **`/` 한 장뿐이다.**
 *
 * 2026-09-09 낮에 `/research`도 공개로 열었다가 저녁에 되돌렸다. 그때 드러난 것:
 * 공개 화면에 비공개 링크가 있으면 방문자는 로그인 벽을 고장으로 읽고, 그 링크는
 * 관리자 경로가 어디인지 알려 주기만 한다. 그리고 "이 주소는 공개인가"를 매번
 * 따져야 하는 구조 자체가 사고의 자리다 — 같은 날 `/api/*`가 그래서 뚫려 있었다.
 *
 * 그래서 규칙을 코드로 고정한다: 공개 페이지는 하나, 그 페이지에서 나가는 링크는
 * 바깥(외부 사이트)뿐이다.
 */

const ROOT = path.join(process.cwd());
const APP = path.join(ROOT, 'src', 'app');

const read = (p: string) => fs.readFileSync(path.join(ROOT, p), 'utf-8');

/** `src/app` 아래 모든 라우트 경로(`page.tsx` 기준). */
function pageRoutes(): string[] {
    const out: string[] = [];
    const walk = (dir: string, route: string) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
            if (e.name === 'api' || e.name.startsWith('.')) continue;
            const full = path.join(dir, e.name);
            if (e.isDirectory()) walk(full, `${route}/${e.name}`);
            else if (e.name === 'page.tsx') out.push(route || '/');
        }
    };
    walk(APP, '');
    return out.sort();
}

/**
 * 미들웨어가 막는 페이지 경로.
 *
 * 2026-09-10까지 이 함수는 **매처를 파싱했다** — 그때는 매처가 곧 차단 목록이라
 * 그게 맞았다. 지금은 매처가 전 경로를 덮고 통과 목록이 따로 있어서(fail-closed),
 * 판정을 그대로 쓴다.
 */
function guardedRoutes(): Set<string> {
    return new Set(pageRoutes().filter((r) => !isOpen(r)));
}

test('공개 페이지는 / 하나뿐이다', () => {
    // `/login`은 로그인 화면 자체라 막을 수 없다(막으면 들어갈 문이 없다).
    const openRoutes = pageRoutes().filter((r) => r !== '/login' && isOpen(r));
    assert.deepEqual(openRoutes, ['/'],
        `공개 페이지가 늘었다: ${openRoutes.join(', ')} — 의도한 것이면 이 테스트를 함께 고칠 것`);
});

test('공개 페이지는 비공개 경로로 링크하지 않는다', () => {
    const body = read('src/app/ShowcaseClient.tsx');
    for (const g of guardedRoutes()) {
        assert.ok(!body.includes(`href="${g}"`) && !body.includes(`href='${g}'`),
            `공개 페이지가 ${g}로 링크한다 — 방문자는 로그인 벽을 고장으로 읽는다`);
        assert.ok(!body.includes(`push('${g}`) && !body.includes(`push(\`${g}`),
            `공개 페이지가 ${g}로 이동시킨다`);
    }
});

test('공개 페이지는 주문 경로를 넘기지 않는다', () => {
    const body = read('src/app/ShowcaseClient.tsx');
    assert.ok(!body.includes('onQuickOrder='),
        'onQuickOrder를 넘기면 공개 화면에 주문 버튼이 생긴다');
});

test('색인 대상은 공개 페이지뿐이다', () => {
    const robots = read('src/app/robots.ts');
    const disallow = [...(robots.match(/disallow:\s*\[([^\]]*)\]/s)?.[1] ?? '')
        .matchAll(/'([^']+)'/g)].map((m) => m[1]);
    assert.ok(disallow.length > 0, 'robots.ts의 disallow를 못 읽었다');
    for (const g of guardedRoutes()) {
        // 접두사로 덮여도 된다 — `/trade`가 `/trade/us`를 같이 막는다.
        assert.ok(disallow.some((d) => g === d || g.startsWith(d + '/')),
            `robots.ts가 ${g}를 막지 않는다 — 로그인 화면이 검색 결과에 뜬다`);
    }
});

test('다운로드 API는 세션 뒤에 있다', () => {
    // `/research`가 비공개로 돌아왔고 이 엔드포인트를 부르는 곳은 그 페이지뿐이다.
    // 보안이 아니라 의도 정합성 — "공개면은 / 한 장"에 예외를 두지 않는다.
    for (const p of ['src/app/api/download/excel/route.ts',
                     'src/app/api/download/report/route.ts']) {
        assert.ok(read(p).includes('getToken'), `${p}에 세션 검사가 없다`);
    }
});

test('공개 페이지가 쓰는 데이터 API는 오리진을 매번 치지 않는다', () => {
    // 걱정거리는 남용이 아니라 **비용**이다. 이 데이터는 누구에게나 같은 값이라
    // 사용자를 세는 것(레이트리밋)보다 오리진을 덜 치는 쪽이 맞다.
    // 2026-09-10까지 stocks/research만 캐시가 없었고, `?t=Date.now()`로 GitHub
    // 캐시까지 무력화해 요청 하나가 오리진 5회였다.
    for (const p of ['src/app/api/stocks/research/route.ts',
                     'src/app/api/simulation/stats/route.ts',
                     'src/app/api/trade/history/route.ts',
                     'src/app/api/simulation/libero-history/route.ts']) {
        assert.ok(read(p).includes('createBucketCache'), `${p}에 신선도 캐시가 없다`);
    }
    // 캐시버스터 유무는 검사하지 않는다 — 문자열이 주석에도 있어서 **설명을
    // 검사하게 된다**(실제로 그렇게 빨개졌다). 오리진을 매번 치지 않는다는
    // 성질은 위 `createBucketCache`가 이미 보장한다.
});

test('보안 헤더가 모든 경로에 붙는다', () => {
    const cfg = read('next.config.js');
    for (const h of ['X-Frame-Options', 'X-Content-Type-Options', 'Referrer-Policy']) {
        assert.ok(cfg.includes(h), `next.config.js에 ${h}가 없다`);
    }
    assert.ok(cfg.includes("source: '/:path*'"), '헤더가 일부 경로에만 붙는다');
});

// ── TRADE_PIN을 검사하는 곳은 전부 잠금을 건다 ──────────────────
//
// 2026-09-10 감사에서 나온 것: 잠금이 `/api/trade/program`에만 있었고
// **실주문을 내는 `/api/trade/order`와 `/api/trade/reservation`에는 없었다.**
// 같은 4자리 PIN을 같은 방식으로 검사하는데 방어는 하나뿐이었다는 뜻이고,
// 세션 하나만 있으면 평균 5,000회로 실계좌 주문에 닿았다.
//
// 규칙이 아니라 게이트로 고정한다 — 주석에 "브루트포스 방어 필수"라고 적혀
// 있었는데도 두 라우트가 빠졌던 것이 이 사고의 전부다.

const PIN_ROUTES = [
    'src/app/api/trade/order/route.ts',
    'src/app/api/trade/program/route.ts',
    'src/app/api/trade/reservation/route.ts',
];

test('TRADE_PIN을 검사하는 라우트를 전부 알고 있다', () => {
    const found: string[] = [];
    const walk = (dir: string) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, e.name);
            if (e.isDirectory()) walk(full);
            else if (e.name === 'route.ts' && fs.readFileSync(full, 'utf-8').includes('TRADE_PIN')) {
                found.push(path.relative(ROOT, full).split(path.sep).join('/'));
            }
        }
    };
    walk(path.join(ROOT, 'src', 'app', 'api'));
    assert.deepEqual(found.sort(), [...PIN_ROUTES].sort(),
        'PIN을 검사하는 라우트가 바뀌었다 — 새로 생겼으면 잠금부터 붙일 것');
});

test('PIN을 검사하는 라우트는 전부 잠금을 건다', () => {
    for (const p of PIN_ROUTES) {
        const body = read(p);
        // **import가 아니라 호출**을 본다 — import만 남기고 호출을 지우면
        // 문자열 검사는 통과한다(변이로 확인했다).
        assert.ok(body.includes('await checkPinRateLimit()'),
            `${p}: 잠금 확인을 호출하지 않는다 — 무제한 시도가 가능하다`);
        assert.ok(body.includes('await recordPinFailure()'),
            `${p}: 실패를 세지 않아 잠금이 영원히 안 걸린다`);
    }
});

test('잠금 구현은 하나다', () => {
    // 사본을 두면 같은 program_pin_lockout.json을 두 구현이 쓰고,
    // 임계값이 갈리는 순간 약한 쪽이 실제 방어선이 된다.
    for (const p of PIN_ROUTES) {
        assert.ok(read(p).includes("from '@/lib/pin-lockout'"),
            `${p}: 공용 잠금을 쓰지 않는다`);
        // 파일명 문자열이 아니라 **구현이 있는지**를 본다 — 주석에 저장소 이름을
        // 적어 두는 것은 정상이고, 그걸 잡으면 게이트가 설명을 검사하게 된다
        // (실제로 그렇게 빨개졌다).
        assert.ok(!read(p).includes('function getPinLock'),
            `${p}: 잠금 저장소 구현이 따로 있다 — 사본이 생겼다`);
    }
});
