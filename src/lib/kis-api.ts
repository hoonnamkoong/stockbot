import axios from 'axios';

// Singleton for Token Management
let ACCESS_TOKEN: string | null = null;

const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim();

// Automatically detect Virtual vs Real based on account number prefix '5'
const DEFAULT_URL = KIS_ACCOUNT_NO.startsWith('5') 
    ? 'https://openapivts.koreainvestment.com:29443' 
    : 'https://openapi.koreainvestment.com:9443';

const KIS_BASE_URL = (process.env.KIS_BASE_URL || DEFAULT_URL).trim();

console.log('[KIS Init] Environment loaded:', {
    hasAppKey: !!KIS_APP_KEY,
    keyLen: KIS_APP_KEY.length,
    keyStart: KIS_APP_KEY.substring(0, 4),
    hasAppSecret: !!KIS_APP_SECRET,
    secretLen: KIS_APP_SECRET.length,
    hasAccountNo: !!KIS_ACCOUNT_NO,
    accountPrefix: KIS_ACCOUNT_NO.substring(0, 1),
    baseUrl: KIS_BASE_URL
});

import fs from 'fs';
import path from 'path';
import os from 'os';

import { fetchFile, saveFile } from './github-db';

// File-based Token Management to prevent EGW00133 (Rate Limit) & SMS Spam
const TOKEN_FILE_LOCAL = path.join(os.tmpdir(), 'token.json');
const TOKEN_FILE_GITHUB = 'data/kis_token.json';

function delay(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function getAccessToken(forceRefresh = false): Promise<string | null> {
    if (!forceRefresh) {
        // 1. Try to read from GitHub (Persistent Storage) first
        try {
            const { data: ghTokenData } = await fetchFile<{ access_token: string, expires_at: string }>(TOKEN_FILE_GITHUB);
            if (ghTokenData) {
                const now = new Date().getTime();
                const expiresAt = new Date(ghTokenData.expires_at).getTime();

                // Give 10 minute buffer to be safe
                if (now < expiresAt - 600000) {
                    console.log("[KIS] Using cached Access Token from GitHub");
                    return ghTokenData.access_token;
                } else {
                    console.log("[KIS] GitHub cached token expired, refreshing...");
                }
            }
        } catch (e) {
            console.warn("[KIS] Failed to check GitHub token cache:", e);
        }
    } else {
        console.log("[KIS] Force Refreshing Access Token...");
    }

    // 2. Fetch New Token from KIS
    console.log("[KIS] Requesting New Access Token from KIS...");
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

            const tokenData = {
                access_token: newToken,
                expires_at: expiresAt.toISOString()
            };

            // 3. Save to GitHub (Persistent)
            // Fire and forget - don't block return
            saveFile(TOKEN_FILE_GITHUB, tokenData, "Update KIS Access Token").then(success => {
                if (success) console.log("[KIS] Token saved to GitHub successfully");
                else console.warn("[KIS] Failed to save token to GitHub");
            });

            // 4. Save to Local (Ephemeral/Fast Cache)
            try {
                const dir = path.dirname(TOKEN_FILE_LOCAL);
                if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
                fs.writeFileSync(TOKEN_FILE_LOCAL, JSON.stringify(tokenData, null, 2), 'utf-8');
            } catch (e) { /* ignore local save error */ }

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

    let token = await getAccessToken();

    let cleanAccount = KIS_ACCOUNT_NO.replace(/-/g, '').trim();
    if (cleanAccount.length === 8) {
        cleanAccount += '01'; // Default Suffix
    }
    if (cleanAccount.length !== 10) {
        throw new Error(`Invalid Account Number Length: ${cleanAccount.length}. Expected 10 digits (8 account + 2 suffix).`);
    }
    const cano = cleanAccount.substring(0, 8);
    const acnt_prdt_cd = cleanAccount.substring(8, 10);
    console.log('[KIS] Account parsed:', { cano, acnt_prdt_cd });

    const url = `${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`;
    const isVTS = KIS_BASE_URL.includes('vts');
    const tr_id = isVTS ? "VTTC8434R" : "TTTC8434R";

    const fetchBalance = async (tokenStr: string) => {
        const headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": `Bearer ${tokenStr}`,
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
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        };

        return axios.get(url, { headers, params });
    };

    try {
        console.log('[KIS] Fetching balance from API...');
        if (!token) throw new Error("AccessToken missing");
        
        let res = await fetchBalance(token);

        // 1. Handle Rate Limit / Gateway
        if (res.data.msg1 && (res.data.msg1.includes('초당') || res.data.msg_cd === 'EGW00133')) {
            console.log("[KIS] Rate Limit/Gateway Error. Retrying in 1.1s...");
            await delay(1100);
            res = await fetchBalance(token);
        }

        // 2. Handle Expired Token (EGW00123)
        if (res.data.msg_cd === 'EGW00123' || (res.data.msg1 && res.data.msg1.includes('만료'))) {
            console.log("[KIS] Token Expired on server. Force refreshing and retrying...");
            const newToken = await getAccessToken(true);
            if (newToken) {
                res = await fetchBalance(newToken);
            }
        }

        if (res.data.rt_cd === '0') {
            console.log('[KIS] Balance fetched successfully');
            const output1 = res.data.output1 || [];
            const output2 = (res.data.output2 || [])[0] || {};

            const holdings: HoldingsItem[] = output1
                .map((item: any) => ({
                    name: item.prdt_name,
                    qty: parseInt(item.hldg_qty),
                    price: parseInt(item.prpr),
                    avg_price: parseFloat(item.pchs_avg_pric),
                    pl_rate: parseFloat(item.evlu_pfls_rt),
                    pl_amount: parseInt(item.evlu_pfls_amt),
                    code: item.pdno
                }))
                .filter((holding: HoldingsItem) => holding.qty > 0); // Filter out sold stocks

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

    let cleanAccount = KIS_ACCOUNT_NO.replace(/-/g, '').trim();
    if (cleanAccount.length === 8) {
        cleanAccount += '01'; // Default Suffix
    }
    if (cleanAccount.length !== 10) {
        throw new Error(`Invalid Account Number Length: ${cleanAccount.length}. Expected 10 digits (8 account + 2 suffix).`);
    }
    const cano = cleanAccount.substring(0, 8);
    const acnt_prdt_cd = cleanAccount.substring(8, 10);
    const isVTS = KIS_BASE_URL.includes('vts');

    let tr_id = '';
    if (side === 'buy') {
        tr_id = isVTS ? 'VTTC0802U' : 'TTTC0802U';
    } else {
        tr_id = isVTS ? 'VTTC0801U' : 'TTTC0801U';
    }

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
