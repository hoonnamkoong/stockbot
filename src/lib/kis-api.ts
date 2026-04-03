import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// --- KIS API Configurations ---
const IS_VIRTUAL = process.env.KIS_IS_VIRTUAL === 'true'; // Defaults to false (Real Investment)
const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();

// Real: https://openapi.koreainvestment.com:9443
// Virtual: https://openapivts.koreainvestment.com:29443
const KIS_BASE_URL = process.env.KIS_BASE_URL || 
    (IS_VIRTUAL 
        ? 'https://openapivts.koreainvestment.com:29443' 
        : 'https://openapi.koreainvestment.com:9443');

// Debug Env Vars (safe log)
const logEnvStatus = () => {
    console.log(`[KIS-API] Mode: ${IS_VIRTUAL ? 'VIRTUAL (Mock)' : 'REAL (Production)'}`);
    console.log(`[KIS-API] BaseURL: ${KIS_BASE_URL}`);
    console.log(`[KIS-API] Config Status: Key=${KIS_APP_KEY ? 'OK(Len:'+KIS_APP_KEY.length+')' : 'MISSING'}, Secret=${KIS_APP_SECRET ? 'OK' : 'MISSING'}, Acc=${KIS_ACCOUNT_NO ? 'OK' : 'MISSING'}`);
};
logEnvStatus();

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

    if (!KIS_APP_KEY || !KIS_APP_SECRET) {
        throw new Error('KIS_APP_KEY 또는 KIS_APP_SECRET이 설정되지 않았습니다.');
    }

    try {
        console.log(`[KIS-API] Requesting new token from ${KIS_BASE_URL}...`);
        const res = await axios.post(`${KIS_BASE_URL}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: KIS_APP_KEY,
            appsecret: KIS_APP_SECRET
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
        const token = await getAccessToken();
        if (!token) throw new Error('KIS API Access Token 발급 실패');

        // Account Number format: 12345678-01
        const accParts = KIS_ACCOUNT_NO.split('-');
        const CANO = accParts[0];
        const ACNT_PRDT_CD = accParts[1] || '01';

        // tr_id mapping
        // 실전: TTTC8434R (주식잔고조회)
        // 모의: VTTC8434R (주식잔고조회)
        const tr_id = IS_VIRTUAL ? 'VTTC8434R' : 'TTTC8434R';

        console.log(`[KIS-API] [${tr_id}] Fetching balance for ${CANO}-${ACNT_PRDT_CD}...`);

        const res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, {
            headers: {
                'Content-Type': 'application/json',
                'authorization': `Bearer ${token}`,
                'appkey': KIS_APP_KEY,
                'appsecret': KIS_APP_SECRET,
                'tr_id': tr_id,
                'custtype': 'P' // 개인
            },
            params: {
                CANO: CANO,
                ACNT_PRDT_CD: ACNT_PRDT_CD,
                AFHR_FLG: 'N', // 시간외단일가여부
                OCCN_TX_FOR_YN: 'N', // 국내외구분
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

        const portfolio = {
            deposit: parseInt(output2.dnca_tot_amt || '0'), 
            total_value: parseInt(output2.tot_evlu_amt || '0'), 
            total_profit: parseInt(output2.evlu_amt_smtl_amt || '0'), 
            profit_rate: parseFloat(output2.evlu_pftd_rt || '0'), 
            stocks: output1.map((s: any) => ({
                code: s.pdno,
                name: s.prdt_name,
                quantity: parseInt(s.hldg_qty),
                price: parseInt(s.prpr),
                avg_buy_price: parseInt(s.pchs_avg_pric),
                total_value: parseInt(s.evlu_amt),
                profit: parseInt(s.evlu_pfls_amt),
                profit_rate: parseFloat(s.evlu_pfls_rt)
            })),
            sync_status: 'success'
        };

        console.log(`[KIS-API] Successfully fetched portfolio: ${portfolio.stocks.length} holdings.`);
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
        const token = await getAccessToken();
        const [cano, prdt_cd] = KIS_ACCOUNT_NO.split('-');
        
        // Buy: Real=TTTC0802U, Mock=VTTC0802U
        // Sell: Real=TTTC0801U, Mock=VTTC0801U
        let tr_id = '';
        if (side === 'buy') {
            tr_id = IS_VIRTUAL ? 'VTTC0802U' : 'TTTC0802U';
        } else {
            tr_id = IS_VIRTUAL ? 'VTTC0801U' : 'TTTC0801U';
        }

        console.log(`[KIS-API] [${tr_id}] Placing ${side} order for ${code}...`);

        const res = await axios.post(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`, {
            CANO: cano,
            ACNT_PRDT_CD: prdt_cd || '01',
            PDNO: code,
            ORD_DVSN: price === 0 ? '01' : '00', // 01 for Market, 00 for Limit
            ORD_QTY: qty.toString(),
            ORD_UNPR: price.toString()
        }, {
            headers: {
                'content-type': 'application/json; charset=utf-8',
                'authorization': `Bearer ${token}`,
                'appkey': KIS_APP_KEY,
                'appsecret': KIS_APP_SECRET,
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
