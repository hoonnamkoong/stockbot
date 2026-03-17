import axios from 'axios';

// Singleton for Token Management
let ACCESS_TOKEN: string | null = null;
let EXPIRES_AT: number = 0;
let TOKEN_PROMISE: Promise<string | null> | null = null;

// [Emergency Fix] Ensure no hidden characters and provided fallback for user's confirmed secret
const FALLBACK_SECRET = 'wEOi2vMr/kQMdpdoQC3z/PFNlPvhY+HZul6PtrLbVT4hZxOR2fS6CGz/bFCX6xFgqSMRhawS7GvQFusddAybQpU8LBthxAaq1LWozlsNC7FkrWeV4z32bLod+oIK5Ae7du/0mQx6DHYgfCw9gwN5V7VX83r1uDa/HvDY4FwQS4GX59Ihmqw=';

let KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim().replace(/\s/g, '');
if (!KIS_APP_SECRET || KIS_APP_SECRET.length < 100) {
    console.warn('[KIS] Using Hardcoded Fallback Secret');
    KIS_APP_SECRET = FALLBACK_SECRET;
}

const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim().replace(/\s/g, '');
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').trim().replace(/\s/g, '');
const KIS_BASE_URL = (process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443').trim().replace(/\s/g, '');

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

import { fetchFile, saveFile } from './github-db';

// File-based Token Management to prevent EGW00133 (Rate Limit) & SMS Spam
const TOKEN_FILE_LOCAL = path.join(os.tmpdir(), 'token.json');
const TOKEN_FILE_GITHUB = 'data/kis_token.json';

function delay(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function getAccessToken(): Promise<string | null> {
    // 1. Check Memory Cache First
    const now = new Date().getTime();
    if (ACCESS_TOKEN && now < EXPIRES_AT - 600000) {
        return ACCESS_TOKEN;
    }

    // 2. Concurrency Control: If a request is already in flight, wait for it
    if (TOKEN_PROMISE) {
        return TOKEN_PROMISE;
    }

    TOKEN_PROMISE = (async () => {
        try {
            // 3. Try Local File Cache (/tmp/kis_token.json) - Fast for warmed lambdas
            const TOKEN_FILE_LOCAL_SHARED = path.join(os.tmpdir(), 'kis_token.json');
            try {
                if (fs.existsSync(TOKEN_FILE_LOCAL_SHARED)) {
                    const localData = JSON.parse(fs.readFileSync(TOKEN_FILE_LOCAL_SHARED, 'utf-8'));
                    const localExpires = new Date(localData.expires_at).getTime();
                    if (now < localExpires - 600000) {
                        console.log("[KIS] Using cached Access Token from local /tmp");
                        ACCESS_TOKEN = localData.access_token;
                        EXPIRES_AT = localExpires;
                        return ACCESS_TOKEN;
                    }
                }
            } catch (e) { /* ignore */ }

            // 4. Try GitHub (Persistent Storage)
            try {
                const { data: ghTokenData } = await fetchFile<{ access_token: string, expires_at: string }>(TOKEN_FILE_GITHUB);

                if (ghTokenData) {
                    const expiresAt = new Date(ghTokenData.expires_at).getTime();
                    if (now < expiresAt - 600000) {
                        console.log("[KIS] Using cached Access Token from GitHub");
                        ACCESS_TOKEN = ghTokenData.access_token;
                        EXPIRES_AT = expiresAt;
                        
                        // Sync back to local /tmp for faster next access
                        try {
                            fs.writeFileSync(TOKEN_FILE_LOCAL_SHARED, JSON.stringify(ghTokenData), 'utf-8');
                        } catch (e) { /* ignore */ }
                        
                        return ACCESS_TOKEN;
                    }
                }
            } catch (e) {
                console.warn("[KIS] GitHub cache missing or expired.");
            }

            // 5. Fetch New Token from KIS
            console.log("[KIS] Requesting New Access Token from KIS...");
            const url = `${KIS_BASE_URL}/oauth2/tokenP`;
            const body = {
                grant_type: 'client_credentials',
                appkey: KIS_APP_KEY,
                appsecret: KIS_APP_SECRET
            };

            const res = await axios.post(url, body, {
                headers: { 'content-type': 'application/json' }
            });

            if (res.status === 200 && res.data.access_token) {
                const newToken = res.data.access_token;
                const expiresIn = res.data.expires_in || 86400; // Default 24h
                const expiresAtDate = new Date(now + (expiresIn * 1000));
                const expiresAtMs = expiresAtDate.getTime();

                const tokenData = {
                    access_token: newToken,
                    expires_at: expiresAtDate.toISOString()
                };

                // Update Memory
                ACCESS_TOKEN = newToken;
                EXPIRES_AT = expiresAtMs;

                // 6. Save Save Save
                // Save locally first (immediate)
                try {
                    fs.writeFileSync(TOKEN_FILE_LOCAL_SHARED, JSON.stringify(tokenData), 'utf-8');
                } catch (e) { /* ignore */ }

                // Save to GitHub in background
                saveFile(TOKEN_FILE_GITHUB, tokenData, "Update KIS Access Token").catch(e => {
                    console.warn("[KIS] GitHub save failed:", e.message);
                });

                return newToken;
            } else {
                throw new Error(`Token Fetch Failed: ${res.status}`);
            }
        } finally {
            // Always clear the promise so next request can retry if needed
            TOKEN_PROMISE = null;
        }
    })();

    return TOKEN_PROMISE;
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
        "INQR_DVSN": "01",
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
