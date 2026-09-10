import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { checkPinRateLimit, recordPinFailure, clearPinFailures } from '@/lib/pin-lockout';
import { placeRealOrder } from '@/lib/kis-api';
import { authorizeManualOrder } from '@/lib/trade-auth';
import { kstTimestamp } from '@/lib/kst';
import { brokerRejection, classifyOrderFailure } from '@/lib/order-error';

/**
 * [V8.9.9.22] Trade Order API (Remote Sync Version)
 * For Vercel, we sync virtual portfolio and trade history with GitHub.
 */

const OWNER = 'hoonnamkoong';
const REPO = 'stockbot';
const BRANCH = 'db-data';
// [Security] 실거래 로그는 public이 아닌 비공개 레포에 보관
const SECRET_REPO = 'stockbot-secret';
const SECRET_BRANCH = 'main';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

async function getFileFromGithub(filePath: string, repo: string = REPO, branch: string = BRANCH) {
    const url = `https://api.github.com/repos/${OWNER}/${repo}/contents/${filePath}?ref=${branch}`;
    const res = await fetch(url, {
        headers: {
            'Authorization': `token ${GITHUB_PAT}`,
            'Accept': 'application/vnd.github.v3+json'
        },
        cache: 'no-store'
    });
    if (res.status === 404) return { sha: null, content: null };
    const data = await res.json();
    const content = JSON.parse(Buffer.from(data.content, 'base64').toString('utf-8'));
    return { sha: data.sha, content };
}

async function updateFileOnGithub(filePath: string, content: any, sha: string | null, message: string, repo: string = REPO, branch: string = BRANCH) {
    const url = `https://api.github.com/repos/${OWNER}/${repo}/contents/${filePath}`;
    const base64Content = Buffer.from(JSON.stringify(content, null, 2)).toString('base64');

    await fetch(url, {
        method: 'PUT',
        headers: {
            'Authorization': `token ${GITHUB_PAT}`,
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            message,
            content: base64Content,
            sha: sha || undefined,
            branch: branch
        })
    });
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, isVirtual, pin, ordType } = body;

        // 1. 인증: 자동화 엔진(webhook) 경로는 기존대로, 사람 경로는 세션 + PIN 둘 다 요구.
        //    판정은 lib에 있다(src/lib/trade-auth.ts) — 라우트는 next/server 때문에
        //    테스트가 import를 못 하는데, 이건 테스트가 있어야 하는 판정이다.
        const authHeader = request.headers.get('Authorization');
        const webhookSecret = process.env.WEBHOOK_SECRET;
        const isAuthorizedByWebhook = webhookSecret && authHeader === `Bearer ${webhookSecret}`;
        // 세션 조회는 웹훅 경로에서 불필요하다 — 판정 전에 미리 부르지 않는다.
        const token = isAuthorizedByWebhook
            ? null
            : await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });

        // PIN 무차별 대입 방어 — **`/api/trade/program`에만 있던 것을 여기도 건다.**
        // 2026-09-10까지 이 라우트는 무제한이었다: 세션 하나만 있으면 4자리 PIN을
        // 평균 5,000회면 뚫고, 그 끝은 실계좌 주문이다.
        //
        // 웹훅 경로(자동화 엔진)는 PIN을 쓰지 않으므로 잠금 대상이 아니다 —
        // 걸면 매매 루프가 남의 실패로 멈춘다.
        if (!isAuthorizedByWebhook) {
            const pinCheck = await checkPinRateLimit();
            if (!pinCheck.allowed) {
                console.error('[API-Order] ❌ PIN 시도 제한 초과');
                return NextResponse.json(
                    { success: false, error: `PIN 시도 제한 초과. ${pinCheck.retryAfterMin}분 후 재시도하세요.` },
                    { status: 429 });
            }
        }

        const verdict = authorizeManualOrder({
            authHeader,
            webhookSecret,
            hasSession: !!token,
            pin,
            tradePin: process.env.TRADE_PIN,
        });
        if (!verdict.ok) {
            // 403만 센다 = 세션은 있는데 PIN이 틀린 경우, 곧 실제로 뚫릴 수 있는 시도다.
            // 401(세션 없음)까지 세면 세션 없는 아무나가 주인을 잠글 수 있다
            // (로그인 잠금에서 같은 이유로 신뢰 디바이스 실패만 센다).
            if (verdict.status === 403) await recordPinFailure();
            console.error(`[API-Order] ❌ Unauthorized order attempt (${verdict.status})`);
            return NextResponse.json({ success: false, error: verdict.error }, { status: verdict.status });
        }
        if (!isAuthorizedByWebhook) await clearPinFailures();

        let result: any;
        const now = kstTimestamp();

        if (isVirtual) {
            // [VIRTUAL] Sync with GitHub (db-data branch)
            const { sha, content: portfolio } = await getFileFromGithub('data/portfolio_virtual.json');
            if (!portfolio) throw new Error('가상 포트폴리오 데이터를 불러올 수 없습니다.');
            
            const tradePrice = Number(price) || 50000; 
            const totalCost = tradePrice * Number(qty);

            if (side === 'buy') {
                if (portfolio.cash < totalCost) throw brokerRejection('가상 예수금이 부족합니다.');
                portfolio.cash -= totalCost;
                if (!portfolio.holdings[code]) {
                    portfolio.holdings[code] = { name: code, qty: 0, avg_price: 0, days_held: 0 };
                }
                const h = portfolio.holdings[code];
                const newTotalCost = (h.qty * h.avg_price) + totalCost;
                h.qty += Number(qty);
                h.avg_price = newTotalCost / h.qty;
            } else {
                if (!portfolio.holdings[code] || portfolio.holdings[code].qty < Number(qty)) {
                    throw brokerRejection('가상 보유 수량이 부족합니다.');
                }
                portfolio.cash += totalCost;
                portfolio.holdings[code].qty -= Number(qty);
                if (portfolio.holdings[code].qty === 0) delete portfolio.holdings[code];
            }

            // Update Virtual Portfolio on GitHub
            await updateFileOnGithub('data/portfolio_virtual.json', portfolio, sha, `[V8.9.9.22] Virtual Trade: ${code} ${side}`);
            result = { status: 'SUCCESS', msg: '가상 주문이 클라우드에 반영되었습니다.' };
        } else {
            // [REAL] Direct KIS REST API
            result = await placeRealOrder(code, Number(qty), Number(price), side,
                                          ordType === 'limit' ? 'limit' : 'market');
            // [V8.9.9.39] 판정 로직 교정: placeRealOrder가 예외 없이 성공하면 rt_cd='0' 상태임
            // KIS 원본 응답에는 status 필드가 없으므로 기존 체크는 버그였음
        }

        // [Common] Sync Trade History to GitHub
        try {
            const { sha: hSha, content: history } = await getFileFromGithub('history.json', SECRET_REPO, SECRET_BRANCH);
            const historyList = Array.isArray(history) ? history : (history?.data || []);
            
            historyList.unshift({
                time: now,
                symbol: code,
                action: side.toUpperCase(),
                price: Number(price) || 0,
                qty: Number(qty),
                type: isVirtual ? 'virtual' : 'real',
                reason: 'Manual Dashboard Trade'
            });

            // Keep last 500 entries
            const prunedHistory = historyList.slice(0, 500);
            await updateFileOnGithub('history.json', prunedHistory, hSha, `[V8.9.9.22] Add History: ${code} ${side}`, SECRET_REPO, SECRET_BRANCH);
        } catch (hErr) {
            console.error('[History Sync Error]', hErr);
        }

        return NextResponse.json({
            success: true,
            data: {
                // KIS order-cash 응답은 ODNO/KRX_FWDG_ORD_ORGNO가 최상위가 아니라
                // output 아래 있다(다른 KIS 콜의 output1/output2와 같은 규약,
                // kis-api.ts의 다른 함수들 참고). 2026-08-05까지 이 라우트만
                // 최상위에서 읽어 실전 주문마다 odno가 항상 'UNKNOWN'으로 빠졌다
                // (E10 주문번호 캡처가 배포 이후 한 번도 성공한 적이 없었다).
                odno: result.output?.ODNO || result.output?.KRX_FWDG_ORD_ORGNO || 'UNKNOWN',
                rt_cd: result.rt_cd || '0',
                msg: result.msg1 || '주문이 성공적으로 접수되었습니다.'
            }
        });
    } catch (error: any) {
        // **거부와 고장을 가른다.** 2026-09-10까지 여기서 모든 예외가
        // `rejected:true` + 200이었고, 파이썬 호출부는 그걸 "시장이 거부했다"로
        // 읽어 경고만 찍고 넘어갔다 — KIS 네트워크 실패도, 코드 버그도.
        //
        // 200으로 돌려주던 이유는 "대시보드에서 에러를 보여주려고"였는데,
        // 두 화면(QuickOrderModal·TradeClient) 다 이미 catch에서
        // `error.response?.data?.error`를 읽는다. 비-200에서도 메시지는 보인다.
        const { rejected, status } = classifyOrderFailure(error);
        console.error(`[API-Order] ❌ 주문 ${rejected ? '거부' : '집행 실패(시스템)'}:`, error.message);

        return NextResponse.json({
            success: false,
            error: error.message || '거래 처리 중 예상치 못한 오류가 발생했습니다.',
            rejected
        }, { status });
    }
}
