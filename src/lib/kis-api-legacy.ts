// This file is a legacy backup of the direct KIS API execution logic.
// It is preserved for future use if migrating back from the Hybrid Mobile Architecture.

import axios from 'axios';
import fs from 'fs';
import path from 'path';
import os from 'os';
import { fetchFile, saveFile } from './github-db';

let ACCESS_TOKEN: string | null = null;
let EXPIRES_AT: number = 0;
let TOKEN_PROMISE: Promise<string | null> | null = null;

const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').replace(/[\r\n\s]+/g, '');
const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').replace(/[\r\n\s]+/g, '');
const KIS_ACCOUNT_NO = (process.env.KIS_ACCOUNT_NO || '').replace(/[\r\n\s]+/g, '');

const KIS_BASE_URL = (process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443').replace(/[\r\n\s]+/g, '');

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

const TOKEN_FILE_LOCAL = path.join(os.tmpdir(), 'token.json');
const TOKEN_FILE_GITHUB = 'data/kis_token.json';

function delay(ms: number) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

export async function getAccessToken(forceRefresh = false): Promise<string | null> {
    const now = new Date();
    const nowTime = now.getTime();

    if (!forceRefresh && ACCESS_TOKEN && nowTime < EXPIRES_AT - 3600000) {
        return ACCESS_TOKEN;
    }

    if (TOKEN_PROMISE && !forceRefresh) {
        return TOKEN_PROMISE;
    }

    TOKEN_PROMISE = (async () => {
        try {
            const TOKEN_FILE_LOCAL_SHARED = path.join(os.tmpdir(), 'kis_token.json');
            
            if (!forceRefresh) {
                try {
                    if (fs.existsSync(TOKEN_FILE_LOCAL_SHARED)) {
                        const localData = JSON.parse(fs.readFileSync(TOKEN_FILE_LOCAL_SHARED, 'utf-8'));
                        if (localData.issued_at) {
                            const issuedAt = new Date(localData.issued_at);
                            if (issuedAt.toDateString() === now.toDateString()) {
                                ACCESS_TOKEN = localData.access_token;
                                EXPIRES_AT = new Date(localData.expires_at).getTime();
                                return ACCESS_TOKEN;
                            }
                        }
                        const localExpires = new Date(localData.expires_at).getTime();
                        if (nowTime < localExpires - 3600000) {
                            ACCESS_TOKEN = localData.access_token;
                            EXPIRES_AT = localExpires;
                            return ACCESS_TOKEN;
                        }
                    }
                } catch (e) { /* ignore */ }

                try {
                    const { data: ghTokenData } = await fetchFile<{ access_token: string, issued_at?: string, expires_at: string }>(TOKEN_FILE_GITHUB);
                    if (ghTokenData) {
                        const issuedAt = ghTokenData.issued_at ? new Date(ghTokenData.issued_at) : null;
                        const expiresAt = new Date(ghTokenData.expires_at).getTime();

                        if ((issuedAt && issuedAt.toDateString() === now.toDateString()) || (nowTime < expiresAt - 3600000)) {
                            ACCESS_TOKEN = ghTokenData.access_token;
                            EXPIRES_AT = expiresAt;
                            try {
                                fs.writeFileSync(TOKEN_FILE_LOCAL_SHARED, JSON.stringify(ghTokenData), 'utf-8');
                            } catch (e) { /* ignore */ }
                            return ACCESS_TOKEN;
                        }
                    }
                } catch (e) { }
            }

            const url = `${KIS_BASE_URL}/oauth2/tokenP`;
            const body = {
                grant_type: 'client_credentials',
                appkey: KIS_APP_KEY,
                appsecret: KIS_APP_SECRET
            };

            const res = await axios.post(url, body, {
                headers: { ...WAF_HEADERS }
            });

            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
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
                    await saveFile(TOKEN_FILE_GITHUB, tokenData, "Update KIS Access Token");
                }
                
                return newToken;
            } else {
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
    raw_output2?: any;
    error?: string;
}

export async function getBalance(): Promise<BalanceData | null> {
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

    const dvsnList = ["02", "01"];
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
            let res = await axios.get(`${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/inquire-balance`, { headers, params });

            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
                lastError = "WAF Blocked (HTML Returned)";
                break;
            }

            if (res.status === 401 || (res.data && res.data.msg_cd === 'EGW00121')) {
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
                if (res.data.msg_cd === 'OPSQ2000') continue;
                else break;
            }
        } catch (e: any) {
            if (e.response && e.response.status === 401) {
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    return getBalance(); 
                }
            }
            lastError = e.message;
            break;
        }
    }

    return { error: `${lastError} | Acc: ${cano}-${acnt_prdt_cd}` } as any;
}

export async function placeOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    const token = await getAccessToken();
    if (!token) throw new Error("No Access Token");

    let cleanAccount = KIS_ACCOUNT_NO.replace(/-/g, '').trim();
    const cano = cleanAccount.substring(0, 8);
    const acnt_prdt_cd = cleanAccount.substring(8, 10) || '01';
    const isVTS = KIS_BASE_URL.includes('vts');

    let tr_id = side === 'buy' ? (isVTS ? 'VTTC0802U' : 'TTTC0802U') : (isVTS ? 'VTTC0801U' : 'TTTC0801U');
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

    for (let i = 0; i < 3; i++) {
        try {
            let res = await axios.post(url, body, { headers });

            if (typeof res.data === 'string' && res.data.toLowerCase().includes('<html')) {
                throw new Error("WAF Blocked (HTML Returned)");
            }

            if (res.status === 401 || (res.data && res.data.msg_cd === 'EGW00121')) {
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    res = await axios.post(url, body, { headers });
                }
            }

            if (res.data.msg1 && (res.data.msg1.includes('초당') || res.data.msg_cd === 'EGW00133')) {
                await delay(1100);
                continue;
            }

            if (res.data.rt_cd === '0') {
                return res.data.output;
            } else {
                throw new Error(res.data.msg1);
            }
        } catch (e: any) {
            if (e.response && e.response.status === 401) {
                const newToken = await getAccessToken(true);
                if (newToken) {
                    headers.authorization = `Bearer ${newToken}`;
                    continue; 
                }
            }
            if (i === 2) throw new Error(e.message || "Order Failed");
            await delay(1000);
        }
    }
}
