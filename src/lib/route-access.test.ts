import { test } from 'node:test';
import assert from 'node:assert';
import fs from 'node:fs';
import path from 'node:path';
import { isOpen, SELF_GUARDED_APIS, SELF_GUARD_EXEMPT } from './route-access.ts';

const ROOT = process.cwd();
const API = path.join(ROOT, 'src', 'app', 'api');
const read = (p: string) => fs.readFileSync(path.join(ROOT, p), 'utf-8');

// ── 경계 ────────────────────────────────────────────────────────────
// 접두사 매칭이 경계를 안 지키면 목록 한 줄이 옆 라우트를 같이 연다.

test('접두사는 경로 경계에서만 맞는다', () => {
    assert.ok(isOpen('/api/simulation/stats'));
    assert.ok(!isOpen('/api/simulation/stats-us'),
        'stats가 stats-us를 열면 미국 심 데이터가 같이 나간다');
    assert.ok(isOpen('/api/trade/history'));
    assert.ok(!isOpen('/api/trade/history-us'));
    assert.ok(!isOpen('/trades'), '/ 하나가 /trades를 열면 안 된다');
});

test('하위 경로는 상위 허용을 물려받는다', () => {
    // 태스커가 부르는 경로다. smart-trigger는 스스로 검사하지 않고
    // /api/cron에 위임한다 — 접두사로 같이 열려야 한다.
    assert.ok(isOpen('/api/cron/smart-trigger'));
    assert.ok(isOpen('/api/auth/session'));
    assert.ok(isOpen('/api/auth/callback/credentials'));
});

test('공개면과 로그인 문은 열려 있다', () => {
    for (const p of ['/', '/login', '/robots.txt']) assert.ok(isOpen(p), `${p}가 막혔다`);
});

test('비공개 화면은 막힌다', () => {
    for (const p of ['/trade', '/trade/us', '/research']) {
        assert.ok(!isOpen(p), `${p}가 열려 있다`);
    }
});

test('끝의 슬래시는 판정을 바꾸지 않는다', () => {
    assert.ok(isOpen('/login/'));
    assert.ok(!isOpen('/trade/'), '슬래시 하나로 우회되면 목록이 무의미하다');
});

// ── 배선 ────────────────────────────────────────────────────────────

/** `src/app/api` 아래 라우트 경로 전부. */
function apiRoutes(): string[] {
    const out: string[] = [];
    const walk = (dir: string, route: string) => {
        for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
            const full = path.join(dir, e.name);
            if (e.isDirectory()) walk(full, `${route}/${e.name}`);
            else if (e.name === 'route.ts') out.push(route);
        }
    };
    walk(API, '/api');
    return out;
}

test('시크릿으로 스스로 검사하는 라우트는 전부 열려 있다', () => {
    // 막히면 세션이 없는 기계(태스커·매매 루프)가 못 들어온다 = 매매가 죽는다.
    for (const r of apiRoutes()) {
        const body = read(path.join('src', 'app', r, 'route.ts').split(path.sep).join('/'));
        if (!/WEBHOOK_SECRET|CRON_SECRET/.test(body)) continue;
        assert.ok(isOpen(r),
            `${r}는 시크릿으로 인증하는데 미들웨어가 막는다 — 기계 경로가 죽는다`);
    }
});

test('스스로 검사한다고 적은 라우트는 실제로 시크릿을 검사한다', () => {
    // 배포 후 실측에서 `/api/stocks/refresh`가 무인증 200으로 나왔다 —
    // "cron이 부른다"는 이유로 목록에 넣었는데 그 라우트는 아무것도 검사하지
    // 않았고, 프로덕션에서는 하는 일도 없었다. **라벨은 붙이는 게 아니라
    // 확인하는 것이다.**
    for (const p of SELF_GUARDED_APIS) {
        if (SELF_GUARD_EXEMPT.includes(p)) continue;
        const dir = path.join(ROOT, 'src', 'app', p);
        const bodies: string[] = [];
        const walk = (d: string) => {
            for (const e of fs.readdirSync(d, { withFileTypes: true })) {
                const full = path.join(d, e.name);
                if (e.isDirectory()) walk(full);
                else if (e.name === 'route.ts') bodies.push(fs.readFileSync(full, 'utf-8'));
            }
        };
        walk(dir);
        assert.ok(bodies.some((b) => /WEBHOOK_SECRET|CRON_SECRET/.test(b)),
            `${p}는 시크릿을 검사하지 않는데 세션 없이 통과한다 — 무인증 공개다`);
    }
});

test('통과 목록에 실재하지 않는 경로가 없다', () => {
    // 낡은 항목이 남으면 나중에 그 아래 생기는 라우트를 조용히 연다.
    for (const p of SELF_GUARDED_APIS) {
        const dir = path.join(ROOT, 'src', 'app', p);
        assert.ok(fs.existsSync(dir), `${p}가 실재하지 않는다 — 목록이 낡았다`);
    }
});

test('공개 페이지가 부르는 API는 전부 열려 있다', () => {
    // 목록에서 빠지면 공개면이 빈 화면이 된다. 소스에서 뽑아 비교한다.
    const body = read('src/app/ShowcaseClient.tsx');
    const called = [...body.matchAll(/fetch\(`(\/api\/[^`?]+)/g)].map((m) => m[1]);
    assert.ok(called.length >= 3, `공개면 fetch를 못 찾았다(${called.length}건) — 정규식이 낡았다`);
    for (const c of called) {
        assert.ok(isOpen(c), `공개면이 ${c}를 부르는데 막혀 있다`);
    }
});

test('미들웨어가 판정을 실제로 쓴다', () => {
    const mw = read('src/middleware.ts');
    assert.ok(mw.includes('isOpen(pathname)'), '미들웨어가 통과 목록을 안 쓴다');
    assert.ok(mw.includes("matcher: ['/((?!_next"),
        '매처가 전 경로를 덮지 않는다 — 빠진 경로는 검사 없이 지나간다');
    assert.ok(mw.includes("status: 401"), 'API가 리다이렉트되면 호출부가 HTML을 성공으로 읽는다');
});
