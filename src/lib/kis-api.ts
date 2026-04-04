import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// --- KIS API Configurations (Lazy Load) ---
const getKISConfig = () => {
    const IS_VIRTUAL = process.env.KIS_IS_VIRTUAL === 'true'; 
    const APP_KEY = (process.env.KIS_APP_KEY || '').trim();
    const APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
    const ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();
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

async function readTokenCache() {
    try {
        const data = await fs.readFile(TOKEN_CACHE_PATH, 'utf-8');
        const cache = JSON.parse(data);
        // Check if config matches (to avoid using tokens from different accounts if keys changed)
        const config = getKISConfig();
        if (cache.appkey === config.APP_KEY && cache.expires_at > Date.now() + 3600000) {
            return cache;
        }
    } catch (e: any) {
        // Cache miss or read error is fine
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
        // Ensure data directory exists for local
        if (!process.env.VERCEL) {
            await fs.mkdir(path.dirname(TOKEN_CACHE_PATH), { recursive: true });
        }
        await fs.writeFile(TOKEN_CACHE_PATH, JSON.stringify(cache, null, 2));
        console.log(`[KIS-API] Token saved to disk cache: ${TOKEN_CACHE_PATH}`);
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
 * KIS OAuth2 Access Token 발급 (Direct)
 */
async function getAccessToken(): Promise<string> {
    const now = Date.now();
    
    // 1. Check Memory Cache
    if (cachedToken && now < tokenExpiry - 3600000) { // 1 hour safety margin
        return cachedToken;
    }

    // 2. Check Disk Cache
    const diskCache = await readTokenCache();
    if (diskCache) {
        console.log(`[KIS-API] Using valid token from disk cache (Expires: ${new Date(diskCache.expires_at).toLocaleString()})`);
        cachedToken = diskCache.access_token;
        tokenExpiry = diskCache.expires_at;
        return cachedToken!;
    }

    const config = getKISConfig();
    if (!config.APP_KEY || !config.APP_SECRET) {
        throw new Error(`KIS Credentials Missing (Key:${!!config.APP_KEY}, Secret:${!!config.APP_SECRET}). Check Vercel Env Vars.`);
    }

    try {
        console.log(`[KIS-API] No valid cache. Requesting NEW token from: ${config.BASE_URL}`);
        const res = await axios.post(`${config.BASE_URL}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: config.APP_KEY,
            appsecret: config.APP_SECRET
        });

        if (res.data.access_token) {
            cachedToken = res.data.access_token;
            const expiresIn = parseInt(res.data.expires_in);
            tokenExpiry = now + (expiresIn * 1000);
            
            // 3. Save to Disk Cache
            await writeTokenCache(cachedToken!, expiresIn);
            
            console.log(`[KIS-API] NEW Token issued successfully. Expires in ${expiresIn}s`);
            return cachedToken!;
        }
        throw new Error(`KIS Token issuance failed: ${res.data.msg_cd || ''} ${res.data.msg1 || ''}`);
    } catch (error: any) {
        const errorData = error.response?.data;
        if (errorData?.error_code === 'EGW00133') {
            console.warn('[KIS-API] Rate Limit EGW00133: Access token issued too frequently. Wait 1 min.');
            throw new Error('한투 API 보완: 1분당 1회 토큰 발급 제한에 걸렸습니다. 잠시 후 다시 조회를 눌러주세요.');
        }
        const errorDetail = errorData ? JSON.stringify(errorData) : error.message;
        console.error('[KIS-API] Token Issuance Error:', errorDetail);
        throw new Error(`인증 토큰 발급 실패: ${errorDetail}`);
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

        const [cano, prdt_cd] = config.ACCOUNT_NO.split('-').map(s => s.trim());
        const CANO = cano;
        const ACNT_PRDT_CD = prdt_cd || '01';

        const tr_id = config.IS_VIRTUAL ? 'VTTC8434R' : 'TTTC8434R';
        console.log(`[KIS-API] [${tr_id}] Fetching balance for ${CANO}-${ACNT_PRDT_CD}...`);

        const fetchBalance = async () => {
            return await axios.get(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, {
                headers: {
                    'Content-Type': 'application/json',
                    'authorization': `Bearer ${token}`,
                    'appkey': config.APP_KEY,
                    'appsecret': config.APP_SECRET,
                    'tr_id': tr_id,
                    'tr_cont': 'N',
                    'custtype': 'P'
                },
                params: {
                    CANO: CANO,
                    ACNT_PRDT_CD: ACNT_PRDT_CD,
                    AFHR_FLG: 'N',
                    OCCN_TX_FOR_YN: 'N',
                    PRDT_TYPE_CD: '01',
                    INQR_DVSN: '02',
                    UNPR_DVSN: '01',
                    FUND_STTL_ICLD_YN: 'N',
                    FNCG_AMT_AUTO_RDPT_YN: 'N',
                    PRCS_DVSN: '00',
                    CTX_AREA_FK100: '',
                    CTX_AREA_NK100: '',
                },
                timeout: 5000 // 5s timeout
            });
        };

        let res: any = null;
        let lastError = '';
        const maxRetries = 3;
        const delays = [500, 1000, 2000];

        for (let i = 0; i <= maxRetries; i++) {
            res = await fetchBalance();
            if (res.data.rt_cd === '0') break; // SUCCESS

            if (res.data.rt_cd === '7' && i < maxRetries) {
                console.warn(`[KIS-API] [${tr_id}] Error 7 (Data changed). Retry ${i+1}/${maxRetries} in ${delays[i]}ms...`);
                await new Promise(resolve => setTimeout(resolve, delays[i]));
                continue;
            }
            
            // If it's another error or we ran out of retries
            lastError = res.data.msg1 || 'Unknown KIS Error';
            break;
        }

        if (res.data.rt_cd !== '0') {
            console.error(`[KIS-API] Balance Inquiry Final Error [${res.data.rt_cd}]:`, lastError);
            return { 
                deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
                error: `KIS API Error: ${lastError} (${res.data.rt_cd})`,
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
export async function placeRealOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    try {
        const config = getKISConfig();
        const token = await getAccessToken();
        const [cano, prdt_cd] = config.ACCOUNT_NO.split('-');
        
        let tr_id = '';
        if (side === 'buy') {
            tr_id = config.IS_VIRTUAL ? 'VTTC0802U' : 'TTTC0802U';
        } else {
            tr_id = config.IS_VIRTUAL ? 'VTTC0801U' : 'TTTC0801U';
        }

        console.log(`[KIS-API] [${tr_id}] Placing ${side} order for ${code}...`);

        const orderBody = {
            CANO: cano,
            ACNT_PRDT_CD: prdt_cd || '01',
            PDNO: code,
            ORD_DVSN: price === 0 ? '01' : '00',
            ORD_QTY: qty.toString(),
            ORD_UNPR: price.toString()
        };

        const hashkey = await getHashKey(orderBody);

        const res = await axios.post(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`, orderBody, {
            headers: {
                'content-type': 'application/json; charset=utf-8',
                'authorization': `Bearer ${token}`,
                'appkey': config.APP_KEY,
                'appsecret': config.APP_SECRET,
                'hashkey': hashkey,
                'tr_id': tr_id,
                'tr_cont': 'N',
                'custtype': 'P'
            }
        });

        if (res.data.rt_cd !== '0') {
             console.error(`[KIS-API] Order Error [${res.data.rt_cd}]:`, res.data.msg1);
             throw new Error(res.data.msg1);
        }

        return { ODNO: res.data.output.ODNO, status: "SUCCESS", msg: res.data.msg1 };
    } catch (error: any) {
        console.error('[KIS-API] Real Order Critical Error:', error.message);
        throw error;
    }
}
