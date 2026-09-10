/**
 * TRADE_PIN 무차별 대입 방어 — **PIN을 검사하는 모든 라우트가 여기를 쓴다.**
 *
 * ## 왜 공용인가 (2026-09-10)
 *
 * 이 잠금은 `/api/trade/program`에만 붙어 있었다. 같은 파일 주석이
 * *"4자리 PIN 하나가 무인 자동매매를 여는 유일한 문 → 브루트포스 방어 필수"*라고
 * 적어 뒀는데, 정작 **실주문을 내는 `/api/trade/order`와 `/api/trade/reservation`
 * 에는 안 붙었다.** 세 라우트가 같은 4자리 PIN을 같은 방식으로 검사하는데
 * 방어는 하나에만 있었다는 뜻이다.
 *
 * 그래서 모듈로 뺐다. 사본을 두면 같은 `program_pin_lockout.json`을 두 구현이
 * 쓰게 되고, 임계값이 갈리는 순간 약한 쪽이 실제 방어선이 된다.
 *
 * ## 저장소가 비공개 레포인 이유
 *
 * 카운터가 프로세스 메모리면 서버리스에서 매 요청이 새 인스턴스라 아무것도 못 센다.
 * `stockbot-secret`은 이미 토큰·원장이 사는 곳이고, 이 파일도 공개되면 안 된다
 * (잠금 상태를 보면 언제 시도가 리셋되는지 알 수 있다).
 */
import { nextLockState } from './login-auth';

const OWNER = 'hoonnamkoong';
const SECRET_REPO = 'stockbot-secret';
const SECRET_BRANCH = 'main';
const PIN_LOCK_PATH = 'program_pin_lockout.json';

export const PIN_MAX_ATTEMPTS = 5;
export const PIN_LOCKOUT_MIN = 10;

type Lock = { fails: number; locked_until: string | null };

const pat = () => process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

async function getPinLock(): Promise<{ sha: string | null; content: Lock }> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${PIN_LOCK_PATH}?ref=${SECRET_BRANCH}`;
    const res = await fetch(url, {
        headers: { Authorization: `token ${pat()}`, Accept: 'application/vnd.github.v3+json' },
        cache: 'no-store',
    });
    if (!res.ok) return { sha: null, content: { fails: 0, locked_until: null } };
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content: { fails: content.fails ?? 0, locked_until: content.locked_until ?? null } };
}

async function putPinLock(content: Lock, sha: string | null): Promise<void> {
    const url = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${PIN_LOCK_PATH}`;
    const body = Buffer.from(JSON.stringify(content, null, 2)).toString('base64');
    await fetch(url, {
        method: 'PUT',
        headers: { Authorization: `token ${pat()}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: 'pin lockout update', content: body, sha: sha || undefined, branch: SECRET_BRANCH }),
    });
}

/**
 * 잠겨 있나. **조회 실패는 통과로 본다** — 가용성 우선이고 PIN 자체가 여전히
 * 방어선이다(로그인 잠금과 같은 선택).
 */
export async function checkPinRateLimit(): Promise<{ allowed: boolean; retryAfterMin: number }> {
    try {
        const { content } = await getPinLock();
        if (content.locked_until) {
            const until = new Date(content.locked_until).getTime();
            if (Date.now() < until) {
                return { allowed: false, retryAfterMin: Math.ceil((until - Date.now()) / 60000) };
            }
        }
        return { allowed: true, retryAfterMin: 0 };
    } catch {
        return { allowed: true, retryAfterMin: 0 };
    }
}

/** 실패 1건. 임계에 닿으면 잠근다. 갱신 실패는 삼킨다(카운터 때문에 주문이 죽으면 안 된다). */
export async function recordPinFailure(): Promise<void> {
    try {
        const { sha, content } = await getPinLock();
        await putPinLock(nextLockState({
            fails: content.fails,
            lockedUntil: content.locked_until,
            maxAttempts: PIN_MAX_ATTEMPTS,
            lockoutMin: PIN_LOCKOUT_MIN,
            now: Date.now(),
        }), sha);
    } catch { /* non-blocking */ }
}

/** 성공했으면 지운다 — 며칠에 걸친 실패가 쌓여 정상 사용 한 번 뒤에 잠기지 않게. */
export async function clearPinFailures(): Promise<void> {
    try {
        const { sha, content } = await getPinLock();
        if (content.fails > 0 || content.locked_until) {
            await putPinLock({ fails: 0, locked_until: null }, sha);
        }
    } catch { /* non-blocking */ }
}

/** 잠금 응답 본문. 세 라우트가 같은 문구를 준다. */
export function lockedResponse(retryAfterMin: number) {
    return { success: false, error: `Too many attempts. Try again in ${retryAfterMin} min.` };
}
