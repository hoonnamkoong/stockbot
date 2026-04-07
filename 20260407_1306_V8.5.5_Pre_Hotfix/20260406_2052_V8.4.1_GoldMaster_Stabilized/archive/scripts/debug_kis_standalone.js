
const fs = require('fs');
const path = require('path');
const axios = require('axios');

// 1. Load Env
const envPath = path.join(process.cwd(), '.env.local');
if (fs.existsSync(envPath)) {
    const lines = fs.readFileSync(envPath, 'utf-8').split('\n');
    lines.forEach(line => {
        const parts = line.split('=');
        if (parts.length >= 2 && !line.startsWith('#')) {
            const key = parts[0].trim();
            const val = parts.slice(1).join('=').trim();
            process.env[key] = val;
        }
    });
}

// 2. Mock or Import? better to copy-paste the KIS logic to be 100% sure we test the logic, 
// OR use ts-node to run the actual file. 
// Given importing TS files in a standalone JS script is hard without setup, 
// I will create a JS version of the logic to verify credentials/logic.

const KIS_APP_KEY = process.env.KIS_APP_KEY;
const KIS_APP_SECRET = process.env.KIS_APP_SECRET;
const KIS_ACCOUNT_NO = process.env.KIS_ACCOUNT_NO;
const KIS_BASE_URL = process.env.KIS_BASE_URL;

console.log("Config:", { KIS_APP_KEY, KIS_BASE_URL, KIS_ACCOUNT_NO });

async function getAccessToken() {
    const url = `${KIS_BASE_URL}/oauth2/tokenP`;
    const body = {
        grant_type: 'client_credentials',
        appkey: KIS_APP_KEY,
        appsecret: KIS_APP_SECRET
    };
    try {
        console.log("Fetching Token...");
        const res = await axios.post(url, body, { headers: { 'content-type': 'application/json' } });
        return res.data.access_token;
    } catch (e) {
        console.error("Token Error:", e.message);
        if (e.response) console.error(e.response.data);
        return null;
    }
}

async function placeOrder() {
    const token = await getAccessToken();
    if (!token) return;

    const [cano, acnt_prdt_cd] = KIS_ACCOUNT_NO.split('-');
    const url = `${KIS_BASE_URL}/uapi/domestic-stock/v1/trading/order-cash`;

    // BUY Samsung
    const tr_id = "VTTC0802U";

    const headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": `Bearer ${token}`,
        "appkey": KIS_APP_KEY,
        "appsecret": KIS_APP_SECRET,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": ""
    };

    const body = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "PDNO": "005930",
        "ORD_DVSN": "01", // Market
        "ORD_QTY": "1",
        "ORD_UNPR": "0",
    };

    try {
        console.log("Sending Order...");
        const res = await axios.post(url, body, { headers });
        console.log("Result:", res.data);
    } catch (e) {
        console.error("Order Error:", e.message);
        if (e.response) console.error(e.response.data);
    }
}

placeOrder();
