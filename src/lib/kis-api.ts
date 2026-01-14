import axios from 'axios';

// Singleton for Token Management
let ACCESS_TOKEN: string | null = null;

const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();
const KIS_BASE_URL = (process.env.KIS_BASE_URL || 'https://openapivts.koreainvestment.com:29443').trim();

console.log('[KIS Init] Environment loaded:', {
    hasAppKey: !!KIS_APP_KEY,
    keyLen: KIS_APP_KEY.length,
    keyStart: KIS_APP_KEY.substring(0, 4),
    hasAppSecret: !!KIS_APP_SECRET,
    secretLen: KIS_APP_SECRET.length,
    hasAccountNo: !!KIS_ACCOUNT_NO,
    baseUrl: KIS_BASE_URL
});

import fs from 'fs';
import path from 'path';
import os from 'os';

// File-based Token Management to prevent EGW00133 (Rate Limit)
// Use /tmp for Vercel compatibility (Read-Only JS env)
const TOKEN_FILE_PATH = path.join(os.tmpdir(), 'token.json');

function delay(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function getAccessToken(): Promise<string | null> {
    // 1. Try to read from file first
    try {
        if (fs.existsSync(TOKEN_FILE_PATH)) {
            const fileData = fs.readFileSync(TOKEN_FILE_PATH, 'utf-8');
            const tokenData = JSON.parse(fileData);

            // Check if token is valid (give 1 minute buffer)
            const now = new Date().getTime();
            const expiresAt = new Date(tokenData.expires_at).getTime();

            if (now < expiresAt - 60000) {
                // console.log("[KIS] Using cached Access Token"); 
                return tokenData.access_token;
            } else {
                console.log("[KIS] Cached token expired, refreshing...");
            }
        }
    } catch (e) {
        console.warn("[KIS] Failed to read token cache, fetching new one.");
    }

    // 2. Fetch New Token
    const url = `${KIS_BASE_URL}/oauth2/tokenP`;
    const body = {
        grant_type: 'client_credentials',
        appkey: KIS_APP_KEY,
        appsecret: KIS_APP_SECRET
    };

    try {
        const res = await axios.post(url, body, {
            headers: { 'content-type': 'application/json' }
        });

        if (res.status === 200 && res.data.access_token) {
            const newToken = res.data.access_token;
            const expiresIn = res.data.expires_in || 86400; // Default 24h

            // Calculate expiration time
            const now = new Date();
            const expiresAt = new Date(now.getTime() + (expiresIn * 1000));

            // Save to file
            const tokenData = {
                access_token: newToken,
                expires_at: expiresAt.toISOString()
            };

            // Ensure data dir exists
            const dir = path.dirname(TOKEN_FILE_PATH);
            if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

            fs.writeFileSync(TOKEN_FILE_PATH, JSON.stringify(tokenData, null, 2), 'utf-8');
            console.log("[KIS] New Access Token retrieved and cached successfully");

            return newToken;
            return newToken;
        } else {
            console.error(`[KIS] Token Fetch Failed: Status ${res.status}`, res.data);
            throw new Error(`Token Fetch Failed: ${res.status} - ${JSON.stringify(res.data)}`);
        }
    } catch (error: any) {
        console.error(`[KIS] Token Fetch Exception:`, error.message);
        if (error.response) {
            console.error("[KIS] Error Response:", error.response.data);
            throw new Error(`Token Fetch Exception: ${error.message} - ${JSON.stringify(error.response.data)}`);
        }
        throw new Error(`Token Fetch Exception: ${error.message}`);
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
}

export interface BalanceData {
    deposit: number;
    total_asset: number;
    holdings: HoldingsItem[];
    raw_output2?: any; // For debugging
}

export async function getBalance(): Promise<BalanceData | null> {
    console.log('[KIS] getBalance called');

    const token = await getAccessToken();
    // if (!token) check removed as getAccessToken throws


    if (!KIS_ACCOUNT_NO.includes('-')) {
        console.error("[KIS] Account No format error. Expected format: 12345678-01, got:", KIS_ACCOUNT_NO);
        return null;
    }

    const [cano, acnt_prdt_cd] = KIS_ACCOUNT_NO.split('-');
    console.log('[KIS] Account parsed:', { cano, acnt_prdt_cd });

    const url = `${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`;
    const tr_id = "VTTC8434R";

    const headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": `Bearer ${token}`,
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
    };

    const params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "N",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "00",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    };

    try {
        console.log('[KIS] Fetching balance from API...');
        let res = await axios.get(url, { headers, params });

        if (res.data.msg1 && (res.data.msg1.includes('초당') || res.data.msg_cd === 'EGW00133')) {
            console.log("[KIS] Rate Limit/Gateway Error. Retrying in 1s...");
            await delay(1100);
            res = await axios.get(url, { headers, params });
        }

        if (res.data.rt_cd === '0') {
            console.log('[KIS] Balance fetched successfully');
            const output1 = res.data.output1 || [];
            const output2 = (res.data.output2 || [])[0] || {};

            const holdings: HoldingsItem[] = output1.map((item: any) => ({
                name: item.prdt_name,
                qty: parseInt(item.hldg_qty),
                price: parseInt(item.prpr),
                avg_price: parseFloat(item.pchs_avg_pric),
                pl_rate: parseFloat(item.evlu_pfls_rt),
                pl_amount: parseInt(item.evlu_pfls_amt),
                code: item.pdno
            }));

            const result = {
                // Use prvs_rcdl_excc_amt (D+2 Provisional) for Real-time Buying Power
                deposit: parseInt(output2.prvs_rcdl_excc_amt || output2.dnca_tot_amt || '0'),
                total_asset: parseInt(output2.tot_evlu_amt || '0'),
                holdings,
                raw_output2: output2
            };

            console.log('[KIS] Returning balance data:', {
                deposit: result.deposit,
                total_asset: result.total_asset,
                holdingsCount: holdings.length
            });

            return result;
        } else {
            const errorMsg = `[KIS] API Error: ${res.data.msg1} (Code: ${res.data.msg_cd})`;
            console.error(errorMsg);
            return { error: errorMsg } as any;
        }
    } catch (e: any) {
        const errorMsg = `[KIS] Exception in getBalance: ${e.message}`;
        console.error(errorMsg);
        if (e.response) {
            console.error("[KIS] Response data:", e.response.data);
        }
        return { error: errorMsg } as any;
    }
}

export async function placeOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    console.log(`[KIS] placeOrder called: ${side} ${code} x ${qty} @ ${price}`);

    const token = await getAccessToken();
    if (!token) {
        console.error('[KIS] placeOrder failed: No Access Token');
        throw new Error("No Access Token");
    }

    const [cano, acnt_prdt_cd] = KIS_ACCOUNT_NO.split('-');
    const tr_id = side === 'buy' ? 'VTTC0802U' : 'VTTC0801U';
    const url = `${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`;

    const headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": `Bearer ${token}`,
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": ""
    };

    const ord_dvsn = price === 0 ? "01" : "00";

    const body = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "PDNO": code,
        "ORD_DVSN": ord_dvsn,
        "ORD_QTY": qty.toString(),
        "ORD_UNPR": price.toString(),
    };

    // Retry Loop (3 times)
    for (let i = 0; i < 3; i++) {
        try {
            console.log(`[KIS] Sending Order (Attempt ${i + 1})...`);
            const res = await axios.post(url, body, { headers });

            if (res.data.msg1 && (res.data.msg1.includes('초당') || res.data.msg_cd === 'EGW00133')) {
                console.log(`[KIS] Order Rate Limit/Gateway Error: ${res.data.msg1}. Retrying in 1s...`);
                await delay(1100);
                continue;
            }

            if (res.data.rt_cd === '0') {
                console.log(`[KIS] Order Success: ${res.data.output.ODNO}`);
                return res.data.output;
            } else {
                console.error(`[KIS] Order API Error: ${res.data.msg1} (Code: ${res.data.msg_cd})`);
                // If it's not a rate limit, throw immediately? No, maybe retry helps? 
                // Usually business errors (no balance) won't be fixed by retry, but let's throw.
                throw new Error(res.data.msg1);
            }
        } catch (e: any) {
            console.error(`[KIS] Order Exception (Attempt ${i + 1}): ${e.message}`);
            if (i === 2) throw new Error(e.message || "Order Failed");
            await delay(1000);
        }
    }
}
