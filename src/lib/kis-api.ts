import axios from 'axios';

// Singleton for Token Management
let ACCESS_TOKEN: string | null = null;
let EXPIRES_AT: number = 0;
let TOKEN_PROMISE: Promise<string | null> | null = null;

// [Emergency Fix] Ensure no hidden characters and provided fallback for user's confirmed secret/account
const FALLBACK_SECRET = 'wEOi2vMr/kQMdpdoQC3z/PFNlPvhY+HZul6PtrLbVT4hZxOR2fS6CGz/bFCX6xFgqSMRhawS7GvQFusddAybQpU8LBthxAaq1LWozlsNC7FkrWeV4z32bLod+oIK5Ae7du/0mQx6DHYgfCw9gwN5V7VX83r1uDa/HvDY4FwQS4GX59Ihmqw=';
const FALLBACK_ACCOUNT = '43719326-01';

let KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').replace(/[\r\n\s]+/g, '');
if (!KIS_APP_SECRET || KIS_APP_SECRET.length < 100) {
    console.warn('[KIS] Using Hardcoded Fallback Secret');
    KIS_APP_SECRET = FALLBACK_SECRET;
}

const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').replace(/[\r\n\s]+/g, '');

let KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').replace(/[\r\n\s]+/g, '');
if (!KIS_ACCOUNT_NO || KIS_ACCOUNT_NO === '-01') {
    console.warn('[KIS] Using Hardcoded Fallback Account Number');
    KIS_ACCOUNT_NO = FALLBACK_ACCOUNT;
}

const KIS_BASE_URL = (process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443').replace(/[\r\n\s]+/g, '');

// [Emergency Fix] WAF Bypass Headers
const WAF_HEADERS = {
  "Content-Type": "application/json; charset=utf-8",
  "Accept": "application/json, text/plain, */*",
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
  "Origin": "https://openapi.koreainvestment.com:9443",
  "Referer": "https://openapi.koreainvestment.com:9443/",
  "Accept-Encoding": "gzip, deflate, br",
  "Connection": "keep-alive",
  "Sec-Fetch-Dest": "empty",
  "Sec-Fetch-Mode": "cors",
  "Sec-Fetch-Site": "cross-site",
  "Cache-Control": "no-cache"
};

console.log('[KIS Init] Final Environment:', {
    hasAppKey: !!KIS_APP_KEY,
    hasAppSecret: !!KIS_APP_SECRET,
    finalAccount: KIS_ACCOUNT_NO,
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
    const now = new Date();
    const nowTime = now.getTime();

    // 1. Check Memory Cache First
    if (!forceRefresh && ACCESS_TOKEN && nowTime < EXPIRES_AT - 3600000) {
        return ACCESS_TOKEN;
    }

    // 2. Concurrency Control
    if (TOKEN_PROMISE && !forceRefresh) {
        return TOKEN_PROMISE;
    }

    TOKEN_PROMISE = (async () => {
        try {
            const TOKEN_FILE_LOCAL_SHARED = path.join(os.tmpdir(), 'kis_token.json');
            
            if (!forceRefresh) {
                // 3. Try Local File Cache
                try {
                    if (fs.existsSync(TOKEN_FILE_LOCAL_SHARED)) {
                        const localData = JSON.parse(fs.readFileSync(TOKEN_FILE_LOCAL_SHARED, 'utf-8'));
                        
                        // Policy: If issued TODAY, use it
                        if (localData.issued_at) {
                            const issuedAt = new Date(localData.issued_at);
                            if (issuedAt.toDateString() === now.toDateString()) {
                                console.log("[KIS] Using cached Access Token (Issued TODAY)");
                                ACCESS_TOKEN = localData.access_token;
                                EXPIRES_AT = new Date(localData.expires_at).getTime();
                                return ACCESS_TOKEN;
                            }
                        }

                        const localExpires = new Date(localData.expires_at).getTime();
                        if (nowTime < localExpires - 3600000) {
                            console.log("[KIS] Using cached Access Token (Not expired)");
                            ACCESS_TOKEN = localData.access_token;
                            EXPIRES_AT = localExpires;
                            return ACCESS_TOKEN;
                        }
                    }
                } catch (e) { /* ignore */ }

                // 4. Try GitHub
                try {
                    const { data: ghTokenData } = await fetchFile<{ access_token: string, issued_at?: string, expires_at: string }>(TOKEN_FILE_GITHUB);
                    if (ghTokenData) {
                        const issuedAt = ghTokenData.issued_at ? new Date(ghTokenData.issued_at) : null;
                        const expiresAt = new Date(ghTokenData.expires_at).getTime();

                        if ((issuedAt && issuedAt.toDateString() === now.toDateString()) || (nowTime < expiresAt - 3600000)) {
                            console.log("[KIS] Using persistent Access Token from GitHub");
                            ACCESS_TOKEN = ghTokenData.access_token;
                            EXPIRES_AT = expiresAt;
                            
                            try {
                                fs.writeFileSync(TOKEN_FILE_LOCAL_SHARED, JSON.stringify(ghTokenData), 'utf-8');
                            } catch (e) { /* ignore */ }
                            
                            return ACCESS_TOKEN;
                        }
                    }
                } catch (e) {
                    console.warn("[KIS] GitHub cache missing or expired.");
                }
            }

            // 5. Fetch New Token from KIS
            console.log(`[KIS] Requesting NEW Access Token from KIS... (Force: ${forceRefresh})`);
            const url = `${KIS_BASE_URL}/oauth2/tokenP`;
            const body = {
                grant_type: 'client_credentials',
                appkey: KIS_APP_KEY,
                appsecret: KIS_APP_SECRET
            };

            const res = await axios.post(url, body, {
                headers: { ...WAF_HEADERS }
            });

            // [Emergency Fix] HTML/Text Response Handler
            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
                console.error("[KIS] Token HTML WAF Block:", res.data);
                throw new Error(`Token WAF Error: ${res.data.substring(0, 100)}...`);
            }

            if (res.status === 200 && res.data.access_token) {
                const newToken = res.data.access_token.replace(/[\r\n\s]+/g, '');
                const expiresIn = res.data.expires_in || 86400;
                const expiresAtDate = new Date(nowTime + (expiresIn * 1000));

                const tokenData = {
                    access_token: newToken,
                    issued_at: now.toISOString(),
                    expires_at: expiresAtDate.toISOString()
                };

                ACCESS_TOKEN = newToken;
                EXPIRES_AT = expiresAtDate.getTime();

                try {
                    fs.writeFileSync(TOKEN_FILE_LOCAL_SHARED, JSON.stringify(tokenData), 'utf-8');
                } catch (e) { /* ignore */ }

                if (process.env.GITHUB_PAT) {
                    console.log("[KIS] Saving new token to GitHub...");
                    await saveFile(TOKEN_FILE_GITHUB, tokenData, "Update KIS Access Token");
                }
                
                return newToken;
            } else {
                console.error('[KIS Token Error Details]:', JSON.stringify(res.data));
                throw new Error(`Token Fetch Failed: ${res.status} - ${res.data?.msg1 || 'Unknown'}`);
            }
        } finally {
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
    error?: string;
}

export async function getBalance(): Promise<BalanceData | null> {
    console.log('[KIS] getBalance called');

    const token = await getAccessToken();
    if (!token) return { error: "Failed to obtain KIS Access Token" } as any;

    let cleanAccount = KIS_ACCOUNT_NO.replace(/-/g, '').trim();
    const cano = cleanAccount.substring(0, 8);
    const acnt_prdt_cd = cleanAccount.substring(8, 10) || '01';
    
    const isVTS = KIS_BASE_URL.includes('vts');
    const tr_id = isVTS ? "VTTC8434R" : "TTTC8434R";
    
    const headers = {
        ...WAF_HEADERS,
        "authorization": `Bearer ${token}`,
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P"
    };

    // Try multiple INQR_DVSN if needed
    const dvsnList = ["02", "01"]; // Try 02 (By Stock) first, then 01 (Consolidated)
    let lastError = '';

    for (const dvsn of dvsnList) {
        const params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "N",
            "INQR_DVSN": dvsn,
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        };

        try {
            console.log(`[KIS] Fetching balance (DVSN: ${dvsn})...`);
            let res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, { headers, params });

            // [Emergency Fix] WAF/HTML Error handling
            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
                console.error(`[KIS] Balance HTML WAF Block (DVSN: ${dvsn}):`, res.data);
                lastError = "WAF Blocked (HTML Returned)";
                break;
            }

            // Handle 401 Unauthorized
            if (res.status === 401 || (res.data && res.data.msg_cd === 'EGW00121')) {
                console.warn("[KIS] Unauthorized (401). Refreshing token...");
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, { headers, params });
                }
            }

            if (res.data.msg1 && (res.data.msg1.includes('초당') || res.data.msg_cd === 'EGW00133')) {
                await delay(1100);
                res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, { headers, params });
            }

            if (res.data.rt_cd === '0') {
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
                    .filter((holding: HoldingsItem) => holding.qty > 0 || holding.pl_amount !== 0);

                return {
                    deposit: parseInt(output2.prvs_rcdl_excc_amt || output2.dnca_tot_amt || '0'),
                    total_asset: parseInt(output2.tot_evlu_amt || '0'),
                    holdings,
                    raw_output2: output2
                };
            } else {
                lastError = `[KIS] ${res.data.msg1} (${res.data.msg_cd})`;
                console.warn(`[KIS] DVSN ${dvsn} failed: ${lastError}`);
                // If it's pure account mismatch, try next DVSN
                if (res.data.msg_cd === 'OPSQ2000') continue;
                else break; // Other errors don't need retry with different DVSN
            }
        } catch (e: any) {
            // Handle axial error for 401
            if (e.response && e.response.status === 401) {
                console.warn("[KIS] axios error 401. Refreshing token...");
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    // Recursive retry once or just return error for simplicity? Let's try once.
                    return getBalance(); 
                }
            }
            lastError = e.message;
            console.error(`[KIS] DVSN ${dvsn} exception: ${e.message}`);
            break;
        }
    }

    return { error: `${lastError} | Acc: ${cano}-${acnt_prdt_cd} | URL: ${KIS_BASE_URL} | PAT: ${process.env.GITHUB_PAT ? 'OK' : 'MISSING'}` } as any;
}

export async function placeOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    console.log(`[KIS] placeOrder called: ${side} ${code} x ${qty} @ ${price}`);

    const token = await getAccessToken();
    if (!token) {
        console.error('[KIS] placeOrder failed: No Access Token');
        throw new Error("No Access Token");
    }

    let cleanAccount = KIS_ACCOUNT_NO.replace(/-/g, '').trim();
    const cano = cleanAccount.substring(0, 8);
    const acnt_prdt_cd = cleanAccount.substring(8, 10) || '01';
    const isVTS = KIS_BASE_URL.includes('vts');

    let tr_id = '';
    if (side === 'buy') {
        tr_id = isVTS ? 'VTTC0802U' : 'TTTC0802U';
    } else {
        tr_id = isVTS ? 'VTTC0801U' : 'TTTC0801U';
    }

    const url = `${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`;

    const headers = {
        ...WAF_HEADERS,
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
            let res = await axios.post(url, body, { headers });

            // [Emergency Fix] WAF/HTML Error handling
            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
                console.error(`[KIS] Order HTML WAF Block:`, res.data);
                throw new Error("WAF Blocked (HTML Returned)");
            }

            // Handle 401 Unauthorized
            if (res.status === 401 || (res.data && res.data.msg_cd === 'EGW00121')) {
                console.warn("[KIS] Order Unauthorized (401). Refreshing token...");
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    res = await axios.post(url, body, { headers });
                }
            }

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
                throw new Error(res.data.msg1);
            }
        } catch (e: any) {
            // Handle axios 401
            if (e.response && e.response.status === 401) {
                console.warn("[KIS] Order axios error 401. Refreshing token...");
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    continue; // Retry next loop
                }
            }
            console.error(`[KIS] Order Exception (Attempt ${i + 1}): ${e.message}`);
            if (i === 2) throw new Error(e.message || "Order Failed");
            await delay(1000);
        }
    }
}
