import axios from 'axios';
import fs from 'fs/promises';
import path from 'path';

// --- KIS API Configurations ---
const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();
const KIS_BASE_URL = process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443';

// Data Paths (Lazy loaded to avoid top-level resolution issues)
const getVirtualPath = () => path.join(process.cwd(), 'data', 'portfolio_virtual.json');
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
export async function getRealPortfolio(): Promise<any> {
    try {
        const token = await getAccessToken();
        if (!token) throw new Error('KIS API Access Token 발급 실패 (ID/Secret 확인 필요)');

        const appKey = process.env.KIS_APP_KEY;
        const appSecret = process.env.KIS_APP_SECRET;
        const accountNo = process.env.KIS_ACCOUNT_NO;

        if (!appKey || !appSecret || !accountNo) {
            throw new Error(`환경 변수 누락: ${!appKey ? 'KIS_APP_KEY ' : ''}${!appSecret ? 'KIS_APP_SECRET ' : ''}${!accountNo ? 'KIS_ACCOUNT_NO' : ''}`);
        }

        // 계좌번호 처리 (8자리-2자리 형식 지원)
        const accParts = accountNo.split('-');
        const CANO = accParts[0];
        const ACNT_PRDT_CD = accParts[1] || '01';

        console.log(`[KIS-API] Fetching balance for ${CANO}-${ACNT_PRDT_CD}...`);

        const res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, {
            headers: {
                'Content-Type': 'application/json',
                'authorization': `Bearer ${token}`,
                'appkey': appKey,
                'appsecret': appSecret,
                'tr_id': 'TTTC8434R', // 실전투자용 잔고조회
            },
            params: {
                CANO: CANO,
                ACNT_PRDT_CD: ACNT_PRDT_CD,
                AFHR_FLG: 'N',
                OCCN_TX_FOR_YN: 'N',
            }
        });

        if (res.data.rt_cd !== '0') {
            const errMsg = res.data.msg1 || 'Unknown KIS Error';
            console.error('[KIS-API] API Response Error:', errMsg);
            return { 
                deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
                error: `KIS API Error: ${errMsg} (${res.data.rt_cd})`,
                sync_status: 'error'
            };
        }

        const data = res.data;
        const output1 = data.output1 || [];
        const output2 = data.output2?.[0] || {};

        const portfolio = {
            deposit: parseInt(output2.dnca_tot_amt || '0'), // 예수금
            total_value: parseInt(output2.tot_evlu_amt || '0'), // 총 평가금액
            total_profit: parseInt(output2.evlu_amt_smtl_amt || '0'), // 총 평가손익
            profit_rate: parseFloat(output2.evlu_pftd_rt || '0'), // 수익률
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

        return portfolio;
    } catch (e: any) {
        console.error('[KIS-API] getRealPortfolio critical error:', e.response?.data || e.message);
        return { 
            deposit: 0, stocks: [], total_value: 0, total_profit: 0, profit_rate: 0,
            error: `Critical Error: ${e.response?.data?.msg1 || e.message}`, 
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
