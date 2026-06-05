import { NextResponse } from 'next/server';
import { getToken } from 'next-auth/jwt';
import { placeRealOrder } from '@/lib/kis-api';

/**
 * [V8.9.9.22] Trade Order API (Remote Sync Version)
 * For Vercel, we sync virtual portfolio and trade history with GitHub.
 */

const OWNER = 'hoonnamkoong';
const REPO = 'stockbot';
const BRANCH = 'db-data';
const GITHUB_PAT = process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

async function getFileFromGithub(filePath: string) {
    const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}?ref=${BRANCH}`;
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

async function updateFileOnGithub(filePath: string, content: any, sha: string | null, message: string) {
    const url = `https://api.github.com/repos/${OWNER}/${REPO}/contents/${filePath}`;
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
            branch: BRANCH
        })
    });
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, side, isVirtual, pin } = body;

        // 1. 인증: 자동화 엔진(webhook) 경로는 기존대로, 사람 경로는 세션 + PIN 둘 다 요구
        const authHeader = request.headers.get('Authorization');
        const webhookSecret = process.env.WEBHOOK_SECRET;
        const isAuthorizedByWebhook = webhookSecret && authHeader === `Bearer ${webhookSecret}`;

        if (!isAuthorizedByWebhook) {
            // 1-1. 세션 검증 (PIN 단독 호출 차단 — 로그인된 세션이어야 함)
            const token = await getToken({ req: request as any, secret: process.env.NEXTAUTH_SECRET });
            if (!token) {
                console.error('[API-Order] ❌ Unauthorized order attempt (No valid session)');
                return NextResponse.json({ success: false, error: 'Invalid TRADING AUTH' }, { status: 401 });
            }
            // 1-2. PIN 검증 (env 필수, 폴백 없음)
            const tradePin = process.env.TRADE_PIN;
            if (!tradePin) {
                console.error('[API-Order] ❌ TRADE_PIN not configured on server');
                return NextResponse.json({ success: false, error: 'Server auth not configured' }, { status: 500 });
            }
            if (pin !== tradePin) {
                console.error('[API-Order] ❌ Unauthorized order attempt (Invalid PIN)');
                return NextResponse.json({ success: false, error: 'Invalid TRADING AUTH' }, { status: 403 });
            }
        }

        let result: any;
        const now = new Date(Date.now() + 9 * 60 * 60 * 1000).toISOString().replace('T', ' ').split('.')[0];

        if (isVirtual) {
            // [VIRTUAL] Sync with GitHub (db-data branch)
            const { sha, content: portfolio } = await getFileFromGithub('data/portfolio_virtual.json');
            if (!portfolio) throw new Error('가상 포트폴리오 데이터를 불러올 수 없습니다.');
            
            const tradePrice = Number(price) || 50000; 
            const totalCost = tradePrice * Number(qty);

            if (side === 'buy') {
                if (portfolio.cash < totalCost) throw new Error('가상 예수금이 부족합니다.');
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
                    throw new Error('가상 보유 수량이 부족합니다.');
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
            result = await placeRealOrder(code, Number(qty), Number(price), side);
            // [V8.9.9.39] 판정 로직 교정: placeRealOrder가 예외 없이 성공하면 rt_cd='0' 상태임
            // KIS 원본 응답에는 status 필드가 없으므로 기존 체크는 버그였음
        }

        // [Common] Sync Trade History to GitHub
        try {
            const { sha: hSha, content: history } = await getFileFromGithub('data/history.json');
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
            await updateFileOnGithub('data/history.json', prunedHistory, hSha, `[V8.9.9.22] Add History: ${code} ${side}`);
        } catch (hErr) {
            console.error('[History Sync Error]', hErr);
        }

        return NextResponse.json({ 
            success: true, 
            data: {
                odno: result.ODNO || result.KRX_FWDG_ORD_ORGNO || 'UNKNOWN',
                rt_cd: result.rt_cd || '0',
                msg: result.msg1 || '주문이 성공적으로 접수되었습니다.'
            }
        });
    } catch (error: any) {
        console.error('[API-Order] ❌ 주문 집행 에러:', error.message);
        
        // [V8.9.9.39 Robustness] 증권사 거절 사유(msg1 등)가 있을 경우 이를 에러 대신 처리
        return NextResponse.json({ 
            success: false, 
            error: error.message || '거래 처리 중 예상치 못한 오류가 발생했습니다.',
            rejected: true
        }, { status: 200 }); // 대시보드에서 가시적으로 에러 메시지를 보여주기 위해 200으로 반환
    }
}
