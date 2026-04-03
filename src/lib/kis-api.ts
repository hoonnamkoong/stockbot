import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// --- KIS API Configurations ---
const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();
const KIS_BASE_URL = process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443';

// Data Paths (Single Source of Truth)
const VIRTUAL_PORTFOLIO_PATH = path.join(process.cwd(), 'data', 'portfolio_virtual.json');
// const DUMMY_REAL_PORTFOLIO_PATH = path.join(process.cwd(), 'data', 'portfolio.json'); // REMOVED

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
    cash?: number; // for virtual
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

    try {
        const res = await axios.post(`${KIS_BASE_URL}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: KIS_APP_KEY,
            appsecret: KIS_APP_SECRET
        });

        if (res.data.access_token) {
            cachedToken = res.data.access_token;
            tokenExpiry = now + (res.data.expires_in - 3600) * 1000;
            return cachedToken!;
        }
        throw new Error('KIS Token issuance failed');
    } catch (error: any) {
        console.error('[KIS-API] Token Error:', error.message);
        throw error;
    }
}

/**
 * [REAL] My Portfolio: 한국투자증권 실시간 잔고 조회
 */
export async function getRealPortfolio(): Promise<PortfolioData> {
    try {
        const token = await getAccessToken();
        const [cano, prdt_cd] = KIS_ACCOUNT_NO.split('-');

        const res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, {
            headers: {
                'content-type': 'application/json; charset=utf-8',
                'authorization': `Bearer ${token}`,
                'appkey': KIS_APP_KEY,
                'appsecret': KIS_APP_SECRET,
                'tr_id': 'TTTC8434R',
                'custtype': 'P'
            },
            params: {
                CANO: cano,
                ACNT_PRDT_CD: prdt_cd || '01',
                AFHR_FLPR_YN: 'N',
                OFL_YN: '',
                INQR_DVSN: '02',
                UNPR_DVSN: '01',
                FUND_STTL_ICRT_YN: 'N',
                FNCG_AMT_AUTO_RDPT_YN: 'N',
                PRCS_DVSN: '00',
                CTX_AREA_FK100: '',
                CTX_AREA_NK100: ''
            }
        });

        const data = res.data;
        if (data.rt_cd !== '0') throw new Error(data.msg1);

        const holdings: HoldingsItem[] = (data.output1 || []).map((item: any) => ({
            name: item.prdt_name || item.pdno || '',
            qty: Number(item.hldg_qty || 0),
            price: Number(item.prpr || 0),
            avg_price: Number(item.pchs_avg_pric || 0),
            pl_rate: Number(item.evlu_pfls_rt || 0),
            pl_amount: Number(item.evlu_pfls_amt || 0),
            code: item.pdno || ''
        }));

        const output2 = data.output2?.[0] || {};
        return {
            deposit: Number(output2.dnca_tot_amt || 0),
            total_asset: Number(output2.tot_evlu_amt || 0),
            holdings,
            sync_status: 'ok',
            last_cached: new Date().toISOString()
        };
    } catch (e: any) {
        console.error('[KIS-API] getRealPortfolio error:', e.message);
        // Do NOT fallback to dummy data automatically. Return the error.
        return { 
            deposit: 0, 
            total_asset: 0, 
            holdings: [], 
            error: `Real API Error: ${e.message}`, 
            sync_status: 'error' 
        };
    }
}

/**
 * [VIRTUAL] Gemini Portfolio: 로컬 JSON 파일 기반 (SSOT)
 */
export async function getVirtualPortfolio(): Promise<PortfolioData> {
    try {
        const data = await fs.readFile(VIRTUAL_PORTFOLIO_PATH, 'utf-8');
        const json = JSON.parse(data);
        
        // Calculate total asset
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
        // Return default if file missing
        return { deposit: 3000000, cash: 3000000, total_asset: 3000000, holdings: {}, trade_log: [], sync_status: 'ok' };
    }
}

/**
 * KIS 실거래 주문 집행 (REAL)
 */
export async function placeRealOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    try {
        const token = await getAccessToken();
        const [cano, prdt_cd] = KIS_ACCOUNT_NO.split('-');
        const tr_id = side === 'buy' ? 'TTTC0802U' : 'TTTC0801U';

        const res = await axios.post(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`, {
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
                'appkey': KIS_APP_KEY,
                'appsecret': KIS_APP_SECRET,
                'tr_id': tr_id,
                'custtype': 'P'
            }
        });

        if (res.data.rt_cd !== '0') throw new Error(res.data.msg1);

        return { ODNO: res.data.output.ODNO, status: "SUCCESS", msg: res.data.msg1 };
    } catch (error: any) {
        console.error('[KIS-API] Real Order Error:', error.message);
        throw error;
    }
}
