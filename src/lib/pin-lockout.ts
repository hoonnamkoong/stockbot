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
 *
 * ## fail-open → fail-closed (2026-09-15)
 *
 * 예전 구현은 조회가 실패하면(`!res.ok`) 조용히 `{fails:0}`을 돌려주고, `catch`에서도
 * `allowed:true`를 돌려줬다. 주석은 *"가용성 우선, PIN 자체가 여전히 방어선"*이라고
 * 적혀 있었지만 **PIN은 4자리다** — 그 자체가 방어선일 수 없고, 시도 횟수를 세는 게
 * 유일한 방어다. PAT 하나만 만료돼도(401) 잠금이 통째로 사라졌다.
 *
 * 그래서 판정은 fail-closed로 뒤집었다. 다만 **404는 장애가 아니라 최초 실행**이므로
 * 통과시킨다 — 구분하지 않으면 파일이 생기기 전까지 아무도 못 들어온다.
 *
 * 기록(`recordPinFailure`/`clearPinFailures`)은 여전히 **던지지 않는다**. 카운터 때문에
 * 주문 경로가 죽으면 안 된다는 원래 판단은 유지한다. 대신 실패를 삼키는 대신 결과값으로
 * 돌려주고 로그를 남긴다 — 안전은 판정 쪽(fail-closed)이 책임진다.
 */
import { nextLockState } from './login-auth.ts';

const OWNER = 'hoonnamkoong';
const SECRET_REPO = 'stockbot-secret';
const SECRET_BRANCH = 'main';
const PIN_LOCK_PATH = 'program_pin_lockout.json';

export const PIN_MAX_ATTEMPTS = 5;
export const PIN_LOCKOUT_MIN = 10;

/** sha 충돌(동시 요청)은 다시 읽고 쓰면 풀린다. 3회면 동시 3건까지 무손실. */
const PUT_ATTEMPTS = 3;

type Lock = { fails: number; locked_until: string | null };

/** 잠금 상태를 읽거나 쓰지 못했다. **"잠금 없음"과 절대 같은 값이 아니다.** */
class PinLockError extends Error {}

const pat = () => process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;
/** 토큰이 섞일 수 있는 값은 절대 넣지 않는다. */
const why = (e: unknown) => (e instanceof Error ? e.message : 'unknown');

const CONTENTS_URL = `https://api.github.com/repos/${OWNER}/${SECRET_REPO}/contents/${PIN_LOCK_PATH}`;

/** 404(최초 실행)만 빈 상태로 본다. 나머지 실패는 전부 예외다. */
async function getPinLock(): Promise<{ sha: string | null; content: Lock }> {
    let res: Response;
    try {
        res = await fetch(`${CONTENTS_URL}?ref=${SECRET_BRANCH}`, {
            headers: { Authorization: `token ${pat()}`, Accept: 'application/vnd.github.v3+json' },
            cache: 'no-store',
        });
    } catch (e) {
        throw new PinLockError(`조회 불가(네트워크): ${why(e)}`);
    }
    if (res.status === 404) return { sha: null, content: { fails: 0, locked_until: null } };
    if (!res.ok) throw new PinLockError(`조회 불가(HTTP ${res.status})`);
    try {
        const data = await res.json();
        const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
        return {
            sha: data.sha ?? null,
            content: { fails: content.fails ?? 0, locked_until: content.locked_until ?? null },
        };
    } catch (e) {
        // 읽긴 했는데 해석이 안 된다 = 상태를 모른다. 모르면 잠근다.
        throw new PinLockError(`조회 불가(본문 해석): ${why(e)}`);
    }
}

/**
 * 읽고-고쳐-쓴다. **PUT 응답을 검사한다** — 예전엔 안 봐서 409(sha 충돌)가 조용히
 * 사라졌고, 동시 20건이 들어오면 1건만 반영돼 `fails:1`로 집계됐다(병렬 시도 무력화).
 *
 * `mutate`가 `null`을 돌려주면 쓸 게 없다는 뜻이다.
 */
async function updatePinLock(mutate: (cur: Lock) => Lock | null, message: string): Promise<void> {
    let lastStatus = 0;
    for (let attempt = 1; attempt <= PUT_ATTEMPTS; attempt++) {
        const { sha, content } = await getPinLock();
        const next = mutate(content);
        if (!next) return;
        let res: Response;
        try {
            res = await fetch(CONTENTS_URL, {
                method: 'PUT',
                headers: { Authorization: `token ${pat()}`, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message,
                    content: Buffer.from(JSON.stringify(next, null, 2)).toString('base64'),
                    sha: sha || undefined,
                    branch: SECRET_BRANCH,
                }),
            });
        } catch (e) {
            throw new PinLockError(`기록 불가(네트워크): ${why(e)}`);
        }
        if (res.ok) return;
        lastStatus = res.status;
        // 409/422 = 그 사이 누가 먼저 썼다. 다시 읽어서 그 위에 쌓는다.
        if (res.status !== 409 && res.status !== 422) throw new PinLockError(`기록 불가(HTTP ${res.status})`);
    }
    throw new PinLockError(`기록 불가(sha 충돌 ${PUT_ATTEMPTS}회, 마지막 HTTP ${lastStatus})`);
}

/**
 * 잠겨 있나. **조회 실패는 잠금으로 본다(fail-closed)** — 파일 상단 주석 참고.
 * 404(최초 실행)만 예외다.
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
    } catch (e) {
        console.error(`[pin-lockout] ❌ 잠금 상태를 못 읽어 차단한다 — ${why(e)}`);
        return { allowed: false, retryAfterMin: PIN_LOCKOUT_MIN };
    }
}

/**
 * 실패 1건. 임계에 닿으면 잠근다.
 *
 * **던지지 않는다** — 카운터 때문에 주문 경로가 죽으면 안 된다. 대신 삼키지도 않는다:
 * 기록 못 했으면 `{recorded:false, error}`로 돌려주고 로그를 남긴다. 호출부는 지금
 * 반환값을 안 보지만(하위 호환), 못 셌다는 사실이 값과 로그 둘 다에 남는다.
 */
export async function recordPinFailure(): Promise<{ recorded: boolean; error?: string }> {
    try {
        await updatePinLock((cur) => nextLockState({
            fails: cur.fails,
            lockedUntil: cur.locked_until,
            maxAttempts: PIN_MAX_ATTEMPTS,
            lockoutMin: PIN_LOCKOUT_MIN,
            now: Date.now(),
        }), 'pin lockout update');
        return { recorded: true };
    } catch (e) {
        const error = why(e);
        console.error(`[pin-lockout] ❌ 실패 카운터를 기록하지 못했다 — ${error}`);
        return { recorded: false, error };
    }
}

/** 성공했으면 지운다 — 며칠에 걸친 실패가 쌓여 정상 사용 한 번 뒤에 잠기지 않게. */
export async function clearPinFailures(): Promise<{ cleared: boolean; error?: string }> {
    try {
        await updatePinLock(
            (cur) => (cur.fails > 0 || cur.locked_until ? { fails: 0, locked_until: null } : null),
            'pin lockout clear',
        );
        return { cleared: true };
    } catch (e) {
        // 해제 실패는 잠금을 남긴다 = 안전한 방향이다. 그래도 주인이 잠길 수 있으니 남긴다.
        const error = why(e);
        console.error(`[pin-lockout] ⚠️ 실패 카운터를 지우지 못했다 — ${error}`);
        return { cleared: false, error };
    }
}

/** 잠금 응답 본문. 세 라우트가 같은 문구를 준다. */
export function lockedResponse(retryAfterMin: number) {
    return { success: false, error: `Too many attempts. Try again in ${retryAfterMin} min.` };
}
