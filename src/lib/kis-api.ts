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

// Token Cache
let cachedToken: string | null = null;
let tokenExpiry: number = 0;

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
 * KIS OAuth2 Access Token 발급 (Direct)
 */
async function getAccessToken(): Promise<string> {
    const now = Date.now();
    if (cachedToken && now < tokenExpiry) return cachedToken;

    const config = getKISConfig();
    if (!config.APP_KEY || !config.APP_SECRET) {
        throw new Error(`KIS Credentials Missing (Key:${!!config.APP_KEY}, Secret:${!!config.APP_SECRET}). Check Vercel Env Vars.`);
    }

    try {
        console.log(`[KIS-API] Requesting token from: ${config.BASE_URL}`);
        const res = await axios.post(`${config.BASE_URL}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: config.APP_KEY,
            appsecret: config.APP_SECRET
        });

        if (res.data.access_token) {
            cachedToken = res.data.access_token;
            // expires_in is usually 86400 (24h). Submarine 1h for safety.
            tokenExpiry = now + (res.data.expires_in - 3600) * 1000;
            console.log(`[KIS-API] Token issued successfully. Expires in ${res.data.expires_in}s`);
            return cachedToken!;
        }
        throw new Error(`KIS Token issuance failed: ${res.data.msg_cd || ''} ${res.data.msg1 || ''}`);
    } catch (error: any) {
        const errorDetail = error.response?.data ? JSON.stringify(error.response.data) : error.message;
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

        if (!config.ACCOUNT_NO) throw new Error('KIS_ACCOUNT_NO 환경변수가 설정되지 않았습니다.');
        
        // Account Number format: 12345678-01
        const accParts = config.ACCOUNT_NO.split('-');
        const CANO = accParts[0];
        const ACNT_PRDT_CD = accParts[1] || '01';

        const tr_id = config.IS_VIRTUAL ? 'VTTC8434R' : 'TTTC8434R';
        console.log(`[KIS-API] [${tr_id}] Fetching balance for ${CANO}-${ACNT_PRDT_CD}...`);

        const res = await axios.get(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, {
            headers: {
                'Content-Type': 'application/json',
                'authorization': `Bearer ${token}`,
                'appkey': config.APP_KEY,
                'appsecret': config.APP_SECRET,
                'tr_id': tr_id,
                'custtype': 'P'
            },
            params: {
                CANO: CANO,
                ACNT_PRDT_CD: ACNT_PRDT_CD,
                AFHR_FLG: 'N',
                OCCN_TX_FOR_YN: 'N',
            }
        });

        // rt_cd '0' is success.
        if (res.data.rt_cd !== '0') {
            const errMsg = res.data.msg1 || 'Unknown KIS Error';
            console.error(`[KIS-API] Balance Inquiry Error [${res.data.rt_cd}]:`, errMsg);
            return { 
                deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
                error: `KIS API Error: ${errMsg} (${res.data.rt_cd})`,
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

        const res = await axios.post(`${config.BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`, {
            CANO: cano,
            ACNT_PRDT_CD: prdt_cd || '01',
            PDNO: code,
            ORD_DVSN: price === 0 ? '01' : '00',
            ORD_QTY: qty.toString(),
            ORD_UNPR: price.toString()
        }, {
            headers: {
                'content-type': 'application/json; charset=utf-8',
                'authorization': `Bearer ${token}`,
                'appkey': config.APP_KEY,
                'appsecret': config.APP_SECRET,
                'tr_id': tr_id,
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
