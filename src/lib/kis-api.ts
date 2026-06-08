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
const parseExpiry = (v: any): number => {
    if (typeof v === 'number') return v; 
    if (typeof v === 'string') return new Date(v).getTime(); 
    return 0;
};

const isTokenValid = (cache: any): boolean => {
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

        for (let i = 0; i <= maxRetries; i++) {
            res = await fetchBalance(currentFK, currentNK);
            
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

        const output1 = res.data.output1 || [];
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
 * KIS 실거래 주문 집행 (REAL/VIRTUAL)
 */
    /**
     * [지시사항 6] 실거래와 가상 매매의 엄격한 물리적 분리
     * 실거래 주문 API 호출은 4월 V2 알고리즘 하에서 절대 금지됩니다.
     */
    export async function placeRealOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
        // [지시사항] 실거래 차단 정책 전면 삭제 및 수동 주문 허용
        console.log(`[KIS-API] 🚀 Executing REAL order: ${side.toUpperCase()} ${code} ${qty} shares at ${price}`);
        
        try {
            const config = getKISConfig();
            const token = await getAccessToken();
            
            // KIS 국내주식 주문/매도 API 호출 (TTTC0802U: 매수, TTTC0801U: 매도)
            const tr_id = side === 'buy' ? 
                (config.IS_VIRTUAL ? 'VTTC0802U' : 'TTTC0802U') : 
                (config.IS_VIRTUAL ? 'VTTC0801U' : 'TTTC0801U');

            const body = {
                "CANO": config.ACCOUNT_NO.slice(0, 8),
                "ACNT_PRDT_CD": config.ACCOUNT_NO.slice(8, 10) || "01",
                "PDNO": code,
                "ORD_DVSN": "01", // 시장가(01) 또는 지정가(00) - 여기서는 시장가 기본
                "ORD_QTY": qty.toString(),
                "ORD_UNPR": side === 'buy' ? "0" : price.toString() // 시장가 매수 시 0
            };

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

        return output1.map((item: any) => ({
            time: `${item.ord_dt?.slice(0,4)}-${item.ord_dt?.slice(4,6)}-${item.ord_dt?.slice(6,8)} ${item.ord_tmd?.slice(0,2)}:${item.ord_tmd?.slice(2,4)}:${item.ord_tmd?.slice(4,6)}`,
            symbol:       `${item.prdt_name}(${item.pdno})`,   // 종목명(코드)
            code:         item.pdno,
            name:         item.prdt_name,
            action:       item.sll_buy_dvsn_cd === '01' ? 'SELL' : 'BUY',
            price:        item.avg_prvs || item.ccld_avg_unpr || '0',  // 체결평균가
            qty:          item.tot_ccld_qty || '0',                     // 체결수량
            amount:       item.tot_ccld_amt || '0',                     // 체결금액
            roi:          item.evlu_pfls_rt || '-',                     // 평가손익률
            type:         'real',
        }));
    } catch (e: any) {
        const msg = e.response?.data?.msg1 || e.message;
        console.error('[KIS-API] getRealTradeHistory Error:', msg);
        return [];
    }
}

