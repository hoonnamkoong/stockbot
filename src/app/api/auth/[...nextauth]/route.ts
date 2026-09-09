import NextAuth from "next-auth"
import CredentialsProvider from "next-auth/providers/credentials"
import { authorizeLogin, nextLockState } from "@/lib/login-auth"

/**
 * 대시보드 로그인.
 *
 * 판정은 `src/lib/login-auth.ts`에 있다(라우트는 node 테스트가 못 읽는다).
 * 여기 남은 것은 잠금 상태의 읽기/쓰기와 NextAuth 배선뿐이다.
 *
 * 잠금 저장소는 비공개 레포다 — `/api/trade/program`의 PIN 잠금과 같은 자리,
 * 같은 모양이다. 저장 헬퍼가 그 라우트와 중복인 것은 알고 있다. 공용으로
 * 빼려면 실거래 경로를 건드려야 해서 별건으로 남긴다.
 */
const OWNER = 'hoonnamkoong';
const SECRET_REPO = 'stockbot-secret';
const SECRET_BRANCH = 'main';
const LOCK_PATH = 'login_lockout.json';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

const MAX_ATTEMPTS = 5;
const LOCKOUT_MIN = 10;

/** 로그인 실패는 어느 쪽이 틀렸는지 알려주지 않는다. */
const LOGIN_FAILED = 'Invalid credentials';

type Lock = { fails: number; locked_until: string | null };
const NO_LOCK: Lock = { fails: 0, locked_until: null };

async function getLock(): Promise<{ sha: string | null; content: Lock }> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${LOCK_PATH}?ref=${SECRET_BRANCH}`;
    const res = await fetch(url, {
        headers: { Authorization: `token ${GITHUB_PAT}`, Accept: 'application/vnd.github.v3+json' },
        cache: 'no-store',
        signal: AbortSignal.timeout(5000),
    });
    if (!res.ok) return { sha: null, content: { ...NO_LOCK } };
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content: { fails: content.fails ?? 0, locked_until: content.locked_until ?? null } };
}

async function putLock(content: Lock, sha: string | null): Promise<void> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${LOCK_PATH}`;
    const body = Buffer.from(JSON.stringify(content, null, 2)).toString('base64');
    await fetch(url, {
        method: 'PUT',
        headers: { Authorization: `token ${GITHUB_PAT}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'login lockout update', content: body, sha: sha || undefined, branch: SECRET_BRANCH }),
        signal: AbortSignal.timeout(5000),
    });
}

const handler = NextAuth({
    providers: [
        CredentialsProvider({
            name: 'Admin Access',
            credentials: {
                password: { label: "Password", type: "password" },
                deviceId: { label: "Device ID", type: "text" }
            },
            async authorize(credentials) {
                // 잠금 조회 실패는 통과로 본다 — 가용성 우선이고, 자격증명 두 겹이
                // 여전히 방어선이다. PIN 잠금과 같은 선택이다.
                let lock: { sha: string | null; content: Lock };
                try {
                    lock = await getLock();
                } catch {
                    lock = { sha: null, content: { ...NO_LOCK } };
                }

                const verdict = authorizeLogin({
                    password: credentials?.password,
                    deviceId: credentials?.deviceId,
                    adminPassword: process.env.ADMIN_PASSWORD,
                    trustedDevices: process.env.TRUSTED_DEVICES,
                    lockedUntil: lock.content.locked_until,
                    now: Date.now(),
                });

                if (verdict.ok) {
                    // 성공했으면 카운터를 지운다. 실패가 며칠에 걸쳐 쌓여 정상 로그인
                    // 한 번 뒤에 잠기는 일이 없게 한다.
                    if (lock.content.fails > 0 || lock.content.locked_until) {
                        try { await putLock({ ...NO_LOCK }, lock.sha); } catch { /* non-blocking */ }
                    }
                    return { id: "1", name: "Admin" };
                }

                if (verdict.reason === 'locked') {
                    throw new Error(`Too many attempts. Try again in ${verdict.retryAfterMin} min.`);
                }
                if (verdict.reason === 'misconfigured') {
                    // 서버 설정 문제다. 자격증명에 대해서는 아무것도 말하지 않는다.
                    throw new Error('Server auth not configured');
                }

                // **신뢰 디바이스에서 온 실패만 센다.** 전역 카운터로 모든 실패를
                // 세면, 공개된 `/login`에 아무나 반복해서 틀려 주인을 영구 잠금시킬 수
                // 있다. 모르는 디바이스는 비밀번호를 맞혀도 못 들어오므로 셀 이유가 없다.
                if (!verdict.deviceTrusted) throw new Error(LOGIN_FAILED);

                try {
                    await putLock(
                        nextLockState({
                            fails: lock.content.fails,
                            lockedUntil: lock.content.locked_until,
                            maxAttempts: MAX_ATTEMPTS,
                            lockoutMin: LOCKOUT_MIN,
                            now: Date.now(),
                        }),
                        lock.sha,
                    );
                } catch { /* 카운터 갱신 실패는 non-blocking */ }

                throw new Error(LOGIN_FAILED);
            }
        })
    ],
    session: {
        strategy: 'jwt'
    },
    pages: {
        signIn: '/login', // Custom login page path
    },
    secret: process.env.NEXTAUTH_SECRET,
})

export { handler as GET, handler as POST }
