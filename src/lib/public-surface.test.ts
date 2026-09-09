import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';

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

/** 미들웨어가 막는 경로(매처에서 `:path*` 꼬리를 뗀 것). */
function guardedRoutes(): Set<string> {
    const m = read('src/middleware.ts').match(/matcher:\s*\[([^\]]*)\]/s);
    assert.ok(m, 'middleware의 matcher를 못 읽었다');
    return new Set(
        [...m![1].matchAll(/"([^"]+)"/g)]
            .map((x) => x[1].replace(/\/:path\*$/, ''))
    );
}

test('공개 페이지는 / 하나뿐이다', () => {
    const guarded = guardedRoutes();
    // `/login`은 로그인 화면 자체라 막을 수 없다(막으면 들어갈 문이 없다).
    const openRoutes = pageRoutes().filter(
        (r) => r !== '/login' && ![...guarded].some((g) => r === g || r.startsWith(g + '/'))
    );
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
    for (const g of guardedRoutes()) {
        assert.ok(robots.includes(`'${g}'`),
            `robots.ts가 ${g}를 막지 않는다 — 로그인 화면이 검색 결과에 뜬다`);
    }
});
