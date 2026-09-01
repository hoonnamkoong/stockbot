/** [V8.9.9.44] KIS Token Recovery Trigger */
import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// --- KIS API Configurations (Lazy Load) ---
const getKISConfig = () => {
    const IS_VIRTUAL = process.env.KIS_IS_VIRTUAL === 'true'; 
    const APP_KEY = (process.env.KIS_APP_KEY || '').trim();
    const APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
    // [V8.9.9.5] 하이픈 제거 - auth.py와 동일하게 '12345678-01' → '1234567801'
    const ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim().replace(/-/g, '');
    const BASE_URL = process.env.KIS_BASE_URL || 
        (IS_VIRTUAL 
            ? 'https://openapivts.koreainvestment.com:29443' 
            : 'https://openapi.koreainvestment.com:9443');

    return { IS_VIRTUAL, APP_KEY, APP_SECRET, ACCOUNT_NO, BASE_URL };
};

const logEnvStatus = () => {
    const config = getKISConfig();
    console.log(`[KIS-API] Mode: ${config.IS_VIRTUAL ? 'VIRTUAL (Mock)' : 'REAL (Production)'}`);
    console.log(`[KIS-API] BaseURL: ${config.BASE_URL}`);
    console.log(`[KIS-API] Config Status: Key=${config.APP_KEY ? 'OK(Len:'+config.APP_KEY.length+')' : 'MISSING'}, Secret=${config.APP_SECRET ? 'OK' : 'MISSING'}, Acc=${config.ACCOUNT_NO ? 'OK' : 'MISSING'}`);
};
// Initial log
if (typeof window === 'undefined') logEnvStatus();

// Data Paths (Lazy loaded)
const getVirtualPath = () => path.join(process.cwd(), 'data', 'portfolio_virtual.json');

// Token Cache (Memory & Disk)
let cachedToken: string | null = null;
let tokenExpiry: number = 0;

const TOKEN_CACHE_PATH = path.join(process.cwd(), 'data', 'kis_token_cache.json');

// --- Authentication Helpers (Global) ---
export const parseExpiry = (v: any): number => {
    // 숫자는 **밀리초**로 본다. epoch '초'가 들어오면 Date.now()와 1000배
    // 어긋나 언제나 '만료'로 읽히고, 그러면 매 런이 토큰을 새로 발급받는다.
    // KIS는 1일 1회 제한이라 그 순간 그날 매매가 통째로 잠긴다.
    if (typeof v === 'number') return v < 1e12 ? v * 1000 : v;
    if (typeof v === 'string') {
        // 오프셋(`+09:00`/`Z`)이 없는 문자열은 **KST로 읽는다.**
        // 이 캐시는 파이썬이 쓰고 TS가 읽는 언어 간 계약인데, 파이썬 쪽
        // (src/trade/auth.py:30-31)은 naive 값을 KST로 간주하도록 명시적으로
        // 방어하고 있다. TS는 `new Date(v)`라 **실행 환경의 로컬 시간**으로
        // 읽었다 — Vercel은 UTC이므로 같은 문자열을 9시간 다르게 해석한다.
        // 지금 형식에는 오프셋이 있어 드러나지 않지만, 생산자가 한 번만
        // 형식을 바꾸면 토큰이 9시간 더 살아 있는 것으로 보이고 그 사이
        // 모든 호출이 401로 죽는다.
        const naive = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(v);
        return new Date(naive ? `${v.replace(' ', 'T')}+09:00` : v).getTime();
    }
    return 0;
};

export const isTokenValid = (cache: any): boolean => {
    if (!cache?.access_token) return false;
    const expiresMs = parseExpiry(cache.expires_at);
    const now = Date.now();
    // 1. 만료 1시간 전까지는 안전하게 유효함
    if (expiresMs > now + 3600000) return true;
    // 2. [V8.9.9.5 Policy] 오늘 발급된 이력이 있다면 유효로 간주 (KIS 1일 1회 제한 대응)
    if (cache.issued_at) {
        const issuedDate = new Date(cache.issued_at).toDateString();
        const todayDate = new Date().toDateString();
        if (issuedDate === todayDate) return true;
    }
    return false;
};

async function readTokenCache() {

    // 1. Try Remote private repo cache (authenticated, for Vercel persistence)
    const ghTokenRead = process.env.GH_PAT || process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;
    if (process.env.VERCEL && ghTokenRead) {
        try {
            const owner = "hoonnamkoong";
            const repo = "stockbot-secret";
            const ghPath = "kis_token_cache.json";
            const branch = "main";
            const url = `https://api.github.com/repos/${owner}/${repo}/contents/${ghPath}?ref=${branch}&t=${Date.now()}`;

            console.log(`[KIS-API] Fetching remote token cache from private repo...`);
            const res = await axios.get(url, { headers: { Authorization: `token ${ghTokenRead}`, Accept: 'application/vnd.github.raw+json', 'Cache-Control': 'no-cache' } });
            const cache = res.data;

            if (isTokenValid(cache)) {
                console.log(`[KIS-API] ✅ 비공개 레포 토큰 유효 - 재사용 (issued_at: ${cache.issued_at})`);
                return cache;
            } else {
                console.log(`[KIS-API] 비공개 레포 토큰 만료됨. 재발급 필요.`);
            }
        } catch (e: any) {
            console.log(`[KIS-API] Remote cache check failed: ${e.message}`);
        }
    }

    // 2. Try Local File Cache
    try {
        const data = await fs.readFile(TOKEN_CACHE_PATH, 'utf-8');
        const cache = JSON.parse(data);
        if (isTokenValid(cache)) {
            console.log(`[KIS-API] ✅ 로컬 캐시 토큰 유효 - 재사용 (issued_at: ${cache.issued_at})`);
            return cache;
        }
    } catch (e: any) {
        // Cache miss is fine
    }
    return null;
}

async function writeTokenCache(token: string, expiresIn: number) {
    try {
        const config = getKISConfig();
        const cache = {
            access_token: token,
            expires_at: Date.now() + (expiresIn * 1000),
            appkey: config.APP_KEY,
            issued_at: new Date().toISOString()
        };
        
        // 1. Local Fallback (Always try)
        try {
            if (!process.env.VERCEL) {
                await fs.mkdir(path.dirname(TOKEN_CACHE_PATH), { recursive: true });
                await fs.writeFile(TOKEN_CACHE_PATH, JSON.stringify(cache, null, 2));
                console.log(`[KIS-API] Token saved to local disk: ${TOKEN_CACHE_PATH}`);
            }
        } catch (e) {}

        // 2. GitHub Persistence (On Vercel)
        const ghToken = process.env.GH_PAT || process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;
        if (process.env.VERCEL && ghToken) {
            try {
                const owner = "hoonnamkoong";
                const repo = "stockbot-secret";
                const path = "kis_token_cache.json";
                const branch = "main";
                
                // First get the SHA of the existing file (required for PUT)
                const getRes = await axios.get(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
                    params: { ref: branch },
                    headers: { Authorization: `token ${ghToken}` }
                });
                const sha = getRes.data.sha;

                // Update the file
                await axios.put(`https://api.github.com/repos/${owner}/${repo}/contents/${path}`, {
                    message: "auth: Update KIS token cache [skip ci]",
                    content: Buffer.from(JSON.stringify(cache, null, 2)).toString('base64'),
                    sha: sha,
                    branch: branch
                }, {
                    headers: { Authorization: `token ${ghToken}` }
                });
                console.log(`[KIS-API] Token successfully synchronized to GitHub branch: ${branch}`);
            } catch (e: any) {
                console.warn(`[KIS-API] GitHub Token sync failed: ${e.message}`);
            }
        }
    } catch (e: any) {
        console.warn(`[KIS-API] Failed to write token cache: ${e.message}`);
    }
}

export interface HoldingsItem {
    name: string;
    qty: number;
    price: number;
    avg_price: number;
    pl_rate: number;
    pl_amount: number;
    code: string;
    days_held?: number;
}

export interface PortfolioData {
    deposit: number;
    deposit_d2?: number;  // D+2 예수금 (매도대금 정산 반영, 가수도정산금액)
    cash?: number;
    total_asset: number;
    holdings: HoldingsItem[] | Record<string, any>;
    trade_log?: any[];
    sync_status?: string;
    last_cached?: string;
    error?: string;
}

/**
 * KIS HashKey 발급 (POST 요청용 무결성 검증)
 */
async function getHashKey(body: any): Promise<string> {
    const config = getKISConfig();
    try {
        const res = await axios.post(`${config.BASE_URL}/uapi/hashkey`, body, {
            headers: {
                'content-type': 'application/json',
                'appkey': config.APP_KEY,
                'appsecret': config.APP_SECRET,
            }
        });
        if (res.data.HASH) return res.data.HASH;
        throw new Error('Hashkey 발급에 실패했습니다.');
    } catch (error: any) {
        console.error('[KIS-API] Hashkey Error:', error.response?.data || error.message);
        throw new Error(`Hashkey 생성 실패: ${error.message}`);
    }
}

/**
 * KIS OAuth2 Access Token 발급 (GitHub Sync Mode)
 * [V8.9.9.39 Logic] Vercel은 더 이상 직접 토큰을 발급하지 않고 깃허브 캐시만 읽습니다.
 */
async function getAccessToken(): Promise<string> {
    const now = Date.now();
    
    // 1. 메모리 캐시 확인 (1시간 여유)
    if (cachedToken && now < tokenExpiry - 3600000) {
        return cachedToken;
    }

    // 2. 디스크(GitHub) 캐시 확인
    console.log('[Token] Checking GitHub token cache...');
    const diskCache = await readTokenCache();
    
    if (isTokenValid(diskCache)) {
        console.log(`[KIS-API] ✨ Using valid token from disk cache (Expires: ${new Date(diskCache.expires_at).toLocaleString()})`);
        cachedToken = diskCache.access_token;
        tokenExpiry = diskCache.expires_at;
        return cachedToken!;
    }

    // 3. [V8.9.9.39 Logic] 직접 발급 대신 GitHub에 갱신 요청
    console.warn('[Token] ❌ No valid token found. Triggering GitHub Action refresh...');
    
    // GitHub Repository Dispatch 호출 (비동기)
    triggerTokenRefresh();

    throw new Error('인증 토큰이 만료되었습니다. GitHub에서 갱신 중입니다. 1분 후 다시 시도해 주세요.');
}

async function triggerTokenRefresh() {
    const owner = process.env.NEXT_PUBLIC_GITHUB_OWNER || 'hoonnamkoong';
    const repo = process.env.NEXT_PUBLIC_GITHUB_REPO || 'stockbot';
    const pat = process.env.GH_PAT || process.env.GITHUB_PAT || process.env.GITHUB_TOKEN;

    if (!pat) {
        console.error('[Token] GH_PAT/GITHUB_PAT is missing. Cannot trigger refresh.');
        return;
    }

    try {
        await axios.post(
            `https://api.github.com/repos/${owner}/${repo}/dispatches`,
            { event_type: 'refresh_token' },
            {
                headers: {
                    'Authorization': `Bearer ${pat}`,
                    'Accept': 'application/vnd.github.v3+json'
                }
            }
        );
        console.log('[Token] ✅ GitHub refresh event dispatched.');
    } catch (err: any) {
        console.error('[Token] ❌ Failed to dispatch:', err.message);
    }
}

/**
 * [REAL] My Portfolio: 한국투자증권 실시간 잔고 조회
 */
export async function getRealPortfolio(): Promise<any> {
    try {
        const config = getKISConfig();
        const token = await getAccessToken();
        if (!token) throw new Error('KIS API Access Token 발급 실패');

        const fullAccount = (config.ACCOUNT_NO || '').replace(/[-\s]/g, '').trim();
        const CANO = fullAccount.slice(0, 8);
        const ACNT_PRDT_CD = fullAccount.slice(8, 10) || '01';

        const tr_id = config.IS_VIRTUAL ? 'VTTC8434R' : 'TTTC8434R';
        // [Cache Busting] Vercel 캐시 및 세션 꼬임 방지를 위한 고유 ID 생성
        const burstId = Date.now();
        console.log(`[KIS-API] [${tr_id}] Fetching balance for ${CANO}-${ACNT_PRDT_CD} [Buster: ${burstId}]...`);

        const fetchBalance = async (fk = '', nk = '') => {
            return await axios.get(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance?t=${burstId}`, {
                headers: {
                    'Content-Type': 'application/json',
                    'Cache-Control': 'no-store, no-cache, must-revalidate',
                    'Pragma': 'no-cache',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': tr_id,
                    'tr_cont': fk ? 'N' : ' ', // 최초 호출 시 공백(' ') 또는 빈 문자열 명시 (KIS 규격)
                    'custtype': 'P'
                },
                params: {
                    CANO: CANO,
                    ACNT_PRDT_CD: ACNT_PRDT_CD,
                    AFHR_FLG: 'N',
                    OCCN_TX_FOR_YN: 'N',
                    PRDT_TYPE_CD: '01',
                    INQR_DVSN: '01', 
                    UNPR_DVSN: '01',
                    FUND_STTL_ICLD_YN: 'N',
                    FNCG_AMT_AUTO_RDPT_YN: 'N',
                    PRCS_DVSN: '01', 
                    CTX_AREA_FK100: fk,
                    CTX_AREA_NK100: nk,
                },
                timeout: 10000 // Timeout 10s
            });
        };

        let res: any = null;
        let lastError = '';
        const maxRetries = 5;
        const delays = [1500, 2500, 3500, 4500, 6000]; // 재시도 지연 시간 대폭 강화

        let currentFK = "";
        let currentNK = "";
        // 페이지별 보유 종목을 누적한다. res를 덮어쓰기만 하면 마지막 페이지만 남아
        // 앞 페이지 종목이 통째로 유실된다(보유 종목이 페이지 경계를 넘을 때 발현).
        const allRows: any[] = [];

        for (let i = 0; i <= maxRetries; i++) {
            res = await fetchBalance(currentFK, currentNK);
            if (Array.isArray(res.data.output1)) allRows.push(...res.data.output1);

            // 1. 성공 시 즉시 중단
            if (res.data.rt_cd === '0') break;

            // 2. 추가 데이터(페이지네이션)가 있는 경우 (7: 실시간, 9: 과거 등)
            if ((res.data.rt_cd === '7' || res.data.rt_cd === '9') && i < maxRetries) {
                console.warn(`[KIS-API] [${tr_id}] Paginated Response ${res.data.rt_cd}. Fetching next page ${i+1}/${maxRetries}...`);
                
                // 연속 키 추출 보강
                currentFK = res.data.ctx_area_fk100 || res.headers['ctx_area_fk100'] || '';
                currentNK = res.data.ctx_area_nk100 || res.headers['ctx_area_nk100'] || '';
                
                if (!currentFK && !currentNK) {
                    console.warn(`[KIS-API] Continuity keys missing in rt_cd ${res.data.rt_cd}. Breaking loop.`);
                    break; 
                }
                
                await new Promise(resolve => setTimeout(resolve, delays[i]));
                continue;
            }
            
            // 3. 그 외 에러 코드(RT_CD != 0, 7, 9) 발생 시 즉시 루프 탈출 (무한 루프 및 SYDB0050 방어)
            lastError = res.data.msg1 || 'Unknown KIS Error';
            console.error(`[KIS-API] Breaking loop due to RT_CD ${res.data.rt_cd}: ${lastError}`);
            break;
        }

        if (res.data.rt_cd !== '0') {
            const { rt_cd, msg_cd, msg1 } = res.data;
            console.error(`[KIS-API ERROR] Balance Inquiry Failed! rt_cd: ${rt_cd}, msg_cd: ${msg_cd}, msg1: ${msg1}`);
            return { 
                deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
                error: `${msg1 || lastError} (${rt_cd})`,
                sync_status: 'error'
            };
        }

        const output1 = allRows;
        const output2 = res.data.output2?.[0] || {};

        // Normalize to match frontend expectations:
        // Frontend uses: holdings[], h.qty, h.avg_price, h.price, h.pl_rate, h.pl_amount, h.code, h.name
        const holdings = output1.map((s: any) => ({
            code: s.pdno,
            name: s.prdt_name,
            qty: parseInt(s.hldg_qty || '0'),
            price: parseInt(s.prpr || '0'),
            avg_price: parseInt(s.pchs_avg_pric || '0'),
            pl_amount: parseInt(s.evlu_pfls_amt || '0'),
            pl_rate: parseFloat(s.evlu_pfls_rt || '0'),
            total_value: parseInt(s.evlu_amt || '0'),
        }));

        const portfolio = {
            deposit: parseInt(output2.dnca_tot_amt || '0'),
            deposit_d2: parseInt(output2.prvs_rcdl_excc_amt || '0'),  // D+2 예수금(가수도정산금액): 매도대금 D+2 편입분 반영
            total_value: parseInt(output2.tot_evlu_amt || '0'),
            total_profit: parseInt(output2.evlu_amt_smtl_amt || '0'),
            profit_rate: parseFloat(output2.evlu_pftd_rt || '0'),
            holdings,  // ← consistent with frontend
            stocks: holdings,  // ← backwards-compat alias
            sync_status: 'success'
        };

        console.log(`[KIS-API] Successfully fetched portfolio: ${holdings.length} holdings, deposit=${portfolio.deposit}`);
        return portfolio;
    } catch (e: any) {
        const errorBody = e.response?.data;
        const msg = errorBody?.msg1 || errorBody?.message || e.message;
        console.error('[KIS-API] getRealPortfolio Critical Error:', errorBody || e.message);
        return { 
            deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
            error: `한투 API 연결 실패: ${msg}`, 
            sync_status: 'error' 
        };
    }
}

/**
 * [VIRTUAL] Gemini Portfolio: 로컬 JSON 파일 기반 (SSOT)
 */
export async function getVirtualPortfolio(): Promise<PortfolioData> {
    try {
        const data = await fs.readFile(getVirtualPath(), 'utf-8');
        const json = JSON.parse(data);
        
        const holdingsMap = json.holdings || {};
        const totalInvestment = Object.values(holdingsMap).reduce((sum: number, h: any) => sum + (h.qty * h.avg_price), 0);
        
        return {
            deposit: json.cash ?? 3000000,
            cash: json.cash ?? 3000000,
            total_asset: (json.cash ?? 3000000) + totalInvestment,
            holdings: holdingsMap,
            trade_log: json.trade_log || [],
            sync_status: 'ok',
            last_cached: new Date().toISOString()
        };
    } catch (e) {
        return { deposit: 3000000, cash: 3000000, total_asset: 3000000, holdings: {}, trade_log: [], sync_status: 'ok' };
    }
}

/**
 * 주문 파라미터 조립 — 순수 함수. I/O 직전까지의 계산을 전부 여기 모은다.
 *
 * 떼어낸 이유: 실제 버그가 이 계산에서 났다(시장가 매도에 단가를 실어 KIS가 거부, 683cc55).
 * 네트워크에 붙어 있으면 그 회귀를 테스트로 막을 수 없다. src/lib/kis-order.test.ts가 지킨다.
 */
export function buildOrderRequest(
    code: string,
    qty: number,
    side: 'buy' | 'sell',
    opts: { accountNo: string; isVirtual: boolean; ordType?: 'market' | 'limit'; limitPrice?: number },
): { trId: string; body: Record<string, string> } {
    // KIS 국내주식 주문 API (TTTC0802U: 매수, TTTC0801U: 매도, V접두사는 모의)
    const trId = side === 'buy'
        ? (opts.isVirtual ? 'VTTC0802U' : 'TTTC0802U')
        : (opts.isVirtual ? 'VTTC0801U' : 'TTTC0801U');

    // 매도는 항상 시장가다. 손절·트레일링은 리스크를 줄이려는 행동이라
    // 체결 자체가 목적이고, 미체결로 남으면 손실이 계속 커진다.
    const limit = side === 'buy' && opts.ordType === 'limit';
    if (limit && !(Number(opts.limitPrice) > 0)) {
        // 조용히 시장가로 떨어뜨리면 "원하는 가격에만 산다"가 소리 없이 깨진다.
        throw new Error('지정가 주문에 단가가 없습니다');
    }

    return {
        trId,
        body: {
            "CANO": opts.accountNo.slice(0, 8),
            "ACNT_PRDT_CD": opts.accountNo.slice(8, 10) || "01",
            "PDNO": code,
            "ORD_DVSN": limit ? "00" : "01",   // 00=지정가, 01=시장가
            "ORD_QTY": qty.toString(),
            // 시장가는 매수·매도 모두 단가 0 필수 (KIS 규칙, 683cc55 회귀 방지)
            "ORD_UNPR": limit ? String(Math.trunc(Number(opts.limitPrice))) : "0",
        },
    };
}

/**
 * KIS 실거래 주문 집행 (REAL/VIRTUAL)
 *
 * [지시사항 6] 실거래와 가상 매매의 엄격한 물리적 분리
 * 실거래 주문 API 호출은 4월 V2 알고리즘 하에서 절대 금지됩니다.
 */
    export async function placeRealOrder(
        code: string, qty: number, price: number, side: 'buy' | 'sell',
        ordType: 'market' | 'limit' = 'market',
    ): Promise<any> {
        // [지시사항] 실거래 차단 정책 전면 삭제 및 수동 주문 허용
        console.log(`[KIS-API] 🚀 Executing REAL order: ${side.toUpperCase()} ${code} ${qty} shares at ${price}`);

        try {
            const config = getKISConfig();
            const token = await getAccessToken();

            const { trId: tr_id, body } = buildOrderRequest(code, qty, side, {
                accountNo: config.ACCOUNT_NO,
                isVirtual: config.IS_VIRTUAL,
                ordType,
                limitPrice: price,
            });

            const hashKey = await getHashKey(body);

            const res = await axios.post(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`, body, {
                headers: {
                    'content-type': 'application/json',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': tr_id,
                    'hashkey': hashKey
                }
            });

            if (res.data.rt_cd !== '0') {
                // KIS 서버의 한글 에러 사유(msg1)를 포함하여 반환
                throw new Error(res.data.msg1 || `KIS 주문 실패 (${res.data.rt_cd})`);
            }

            return res.data;
        } catch (e: any) {
            const msg = e.response?.data?.msg1 || e.message;
            console.error(`[KIS-API] Order Failed: ${msg}`);
            throw new Error(msg);
        }
    }

// --- Realized ROI 조인 (일별체결 SELL 행 ↔ 기간별매매손익 버킷) ---
export type RealFill = {
    action: 'BUY' | 'SELL';
    code: string;
    time: string;
    qty: string | number;
    roi?: string;
    roiAmount?: number;
    [k: string]: any;
};

export type ProfitEntry = { sellQty: number; roiPct: string; roiAmount: number };

/**
 * 각 SELL 체결 행에 실현손익(roi %, roiAmount 원)을 FIFO로 매칭한다.
 * 원가를 확보 못 한 SELL은 값을 붙이지 않는다(측정 불가). BUY는 그대로 통과.
 */
export function matchRealizedRoi(
    fills: RealFill[],
    buckets: Map<string, ProfitEntry[]>,
): RealFill[] {
    // 소진 상태를 훼손하지 않도록 버킷을 얕게 복제
    const remaining = new Map<string, ProfitEntry[]>();
    buckets.forEach((v, k) => {
        remaining.set(k, v.map(e => ({ ...e })));
    });

    const signedRate = (r: number): string =>
        (r >= 0 ? '+' : '') + r.toFixed(1);

    return fills.map((f) => {
        const out: RealFill = { ...f };
        if (f.action !== 'SELL') return out;

        const yyyymmdd = String(f.time).slice(0, 10).replace(/-/g, '');
        const key = `${f.code}_${yyyymmdd}`;
        const entries = remaining.get(key);
        let need = Number(f.qty) || 0;
        if (!entries || need <= 0) return out;

        const available = entries.reduce((s, e) => s + e.sellQty, 0);
        if (available < need) return out; // 원가 부족 → 측정 불가

        let pnlSum = 0;
        let rateWeighted = 0;
        const totalQty = need;
        for (const e of entries) {
            if (need <= 0) break;
            if (e.sellQty <= 0) continue;
            const take = Math.min(need, e.sellQty);
            const takenAmt = Math.round(e.roiAmount * (take / e.sellQty));
            pnlSum += takenAmt;
            rateWeighted += (parseFloat(e.roiPct) || 0) * (take / totalQty);
            e.roiAmount -= takenAmt; // 남은 금액을 소진 수량과 동기화(과다계상 방지)
            e.sellQty -= take;
            need -= take;
        }
        out.roiAmount = pnlSum;
        out.roi = signedRate(rateWeighted);
        return out;
    });
}

/**
 * 기간별 매매손익현황(TTTC8715R)으로 매도 건별 실현손익을 조회해
 * `종목코드_매매일자(yyyymmdd)` 키의 버킷 Map으로 반환한다.
 * 모의투자 미지원/조회 실패 시 빈 Map(→ 전체 "측정 불가").
 */
export async function getRealizedProfitBuckets(
    fromDateStr: string,
    toDateStr: string,
): Promise<{ ok: boolean; buckets: Map<string, ProfitEntry[]> }> {
    // **조회 실패와 '그 기간에 매도가 없음'을 반드시 가른다.**
    // 예전에는 둘 다 빈 Map이라 호출부가 구분할 수 없었고, 화면은 매도가 정말
    // 없는 날에도 '측정 불가'를 띄웠다 — 그러면 진짜 조회 실패를 알아챌 방법이
    // 사라진다. Python 쪽(src/trade/realized_pnl.py)은 같은 구분을 이미 한다.
    const buckets = new Map<string, ProfitEntry[]>();
    try {
        const config = getKISConfig();
        if (config.IS_VIRTUAL) {
            // 모의투자는 이 TR을 지원하지 않는다. 실패로 떨어뜨린다 — 0건으로
            // 읽으면 '매도가 없었다'가 되어 없는 사실을 만든다.
            console.warn('[KIS-API] 모의투자: 기간별매매손익(TTTC8715R) 미지원 → 측정 불가');
            return { ok: false, buckets };
        }
        const token = await getAccessToken();
        const fullAccount = (config.ACCOUNT_NO || '').replace(/[-\s]/g, '').trim();
        const CANO = fullAccount.slice(0, 8);
        const ACNT_PRDT_CD = fullAccount.slice(8, 10) || '01';

        const res = await axios.get(
            `${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-period-trade-profit`,
            {
                headers: {
                    'Content-Type': 'application/json',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': 'TTTC8715R',
                    'custtype': 'P',
                },
                params: {
                    CANO,
                    ACNT_PRDT_CD,
                    SORT_DVSN: '00',
                    PDNO: '',
                    INQR_STRT_DT: fromDateStr,
                    INQR_END_DT: toDateStr,
                    CBLC_DVSN: '00',
                    CTX_AREA_FK100: '',
                    CTX_AREA_NK100: '',
                },
                timeout: 10000,
            },
        );

        if (res.data.rt_cd !== '0') {
            console.error(`[KIS-API] 매매손익 조회 실패: ${res.data.msg1}`);
            return { ok: false, buckets };
        }

        const output1: any[] = res.data.output1 || [];
        console.log(`[KIS-API] 매매손익 ${output1.length}건 조회 완료`);
        if (output1[0]) console.log('[KIS-API] 매매손익 샘플 키:', JSON.stringify(output1[0]));

        for (const item of output1) {
            // ↓ 필드명은 첫 실호출 로그로 확정 (초안: KIS 문서 기준)
            const code: string = item.pdno;
            const dt: string = item.trad_dt;                 // yyyymmdd
            const sellQty = Number(item.sll_qty || 0);       // 매도수량
            if (!code || !dt || sellQty <= 0) continue;
            if (item.rlzt_pfls == null || item.pfls_rt == null) continue; // 필드 부재 = 측정 실패, 가짜 0 금지
            const roiAmount = Number(item.rlzt_pfls);        // 실현손익(원)
            const rate = Number(item.pfls_rt);               // 손익률(%)
            if (Number.isNaN(roiAmount) || Number.isNaN(rate)) continue;
            const key = `${code}_${dt}`;
            const roiPct = (rate >= 0 ? '+' : '') + rate.toFixed(1);
            const entry: ProfitEntry = { sellQty, roiPct, roiAmount };
            const arr = buckets.get(key);
            if (arr) arr.push(entry); else buckets.set(key, [entry]);
        }
        // 여기까지 왔으면 조회는 성공했다. buckets가 비어 있어도 그건
        // '그 기간에 매도가 없었다'는 **확정된 사실**이지 측정 실패가 아니다.
        return { ok: true, buckets };
    } catch (e: any) {
        const msg = e.response?.data?.msg1 || e.message;
        console.error('[KIS-API] getRealizedProfitBuckets Error:', msg);
        return { ok: false, buckets };
    }
}

/**
 * [V50.1] KIS 당일/기간별 체결 내역 조회
 * API: /uapi/domestic-stock/v1/trading/inquire-daily-ccld (TTTC8001R)
 * 반환: 종목명, 체결가, 체결수량, 매수/매도 구분 포함
 */
export async function getRealTradeHistory(startDate?: string, endDate?: string): Promise<any[]> {
    try {
        const config = getKISConfig();
        const token = await getAccessToken();

        const fullAccount = (config.ACCOUNT_NO || '').replace(/[-\s]/g, '').trim();
        const CANO = fullAccount.slice(0, 8);
        const ACNT_PRDT_CD = fullAccount.slice(8, 10) || '01';

        // 기본값: 오늘 ~ 30일 전
        const today = new Date(Date.now() + 9 * 60 * 60 * 1000); // KST
        const toDateStr = endDate || today.toISOString().slice(0, 10).replace(/-/g, '');
        const from = new Date(today);
        from.setDate(from.getDate() - 30);
        const fromDateStr = startDate || from.toISOString().slice(0, 10).replace(/-/g, '');

        const tr_id = config.IS_VIRTUAL ? 'VTTC8001R' : 'TTTC8001R';
        console.log(`[KIS-API] [${tr_id}] 체결 내역 조회: ${fromDateStr} ~ ${toDateStr}`);

        const res = await axios.get(
            `${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-daily-ccld`,
            {
                headers: {
                    'Content-Type': 'application/json',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': tr_id,
                    'custtype': 'P',
                },
                params: {
                    CANO,
                    ACNT_PRDT_CD,
                    INQR_STRT_DT: fromDateStr,    // 조회 시작일 (YYYYMMDD)
                    INQR_END_DT: toDateStr,        // 조회 종료일 (YYYYMMDD)
                    SLL_BUY_DVSN_CD: '00',         // 00: 전체, 01: 매도, 02: 매수
                    INQR_DVSN: '00',               // 00: 역순(최신→과거)
                    PDNO: '',
                    CCLD_DVSN: '01',               // 01: 체결만
                    ORD_GNO_BRNO: '',
                    ODNO: '',
                    INQR_DVSN_3: '00',
                    INQR_DVSN_1: '',
                    CTX_AREA_FK100: '',
                    CTX_AREA_NK100: '',
                },
                timeout: 10000,
            }
        );

        if (res.data.rt_cd !== '0') {
            console.error(`[KIS-API] 체결 내역 조회 실패: ${res.data.msg1}`);
            return [];
        }

        const output1: any[] = res.data.output1 || [];
        console.log(`[KIS-API] 체결 내역 ${output1.length}건 조회 완료`);

        const fills = output1.map((item: any) => ({
            time: `${item.ord_dt?.slice(0,4)}-${item.ord_dt?.slice(4,6)}-${item.ord_dt?.slice(6,8)} ${item.ord_tmd?.slice(0,2)}:${item.ord_tmd?.slice(2,4)}:${item.ord_tmd?.slice(4,6)}`,
            symbol:       `${item.prdt_name}(${item.pdno})`,   // 종목명(코드)
            code:         item.pdno,
            name:         item.prdt_name,
            action:       (item.sll_buy_dvsn_cd === '01' ? 'SELL' : 'BUY') as 'SELL' | 'BUY',
            price:        item.avg_prvs || item.ccld_avg_unpr || '0',  // 체결평균가
            qty:          item.tot_ccld_qty || '0',                     // 체결수량
            amount:       item.tot_ccld_amt || '0',                     // 체결금액
            type:         'real',
        }));

        // 매도 건에 실현손익(roi %, roiAmount 원) 조인
        // 여기서는 ok를 따로 쓰지 않는다 — 조회가 실패하면 buckets가 비어
        // matchRealizedRoi가 해당 매도 행에 roi를 안 붙인다(=값 없음).
        const { buckets } = await getRealizedProfitBuckets(fromDateStr, toDateStr);
        return matchRealizedRoi(fills, buckets);
    } catch (e: any) {
        const msg = e.response?.data?.msg1 || e.message;
        console.error('[KIS-API] getRealTradeHistory Error:', msg);
        return [];
    }
}

