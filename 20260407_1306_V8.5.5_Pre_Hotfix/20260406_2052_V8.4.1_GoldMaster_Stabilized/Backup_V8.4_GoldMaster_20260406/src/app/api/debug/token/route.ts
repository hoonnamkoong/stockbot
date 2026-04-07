import { NextResponse } from 'next/server';
import axios from 'axios';
import os from 'os';

export const dynamic = 'force-dynamic';

export async function GET() {
    const KIS_APP_KEY = (process.env.KIS_APP_KEY || '').trim();
    const KIS_APP_SECRET = (process.env.KIS_APP_SECRET || '').trim();
    const KIS_BASE_URL = (process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443').trim();

    try {
        const body = {
            grant_type: 'client_credentials',
            appkey: KIS_APP_KEY,
            appsecret: KIS_APP_SECRET
        };

        const res = await axios.post(`${KIS_BASE_URL}/oauth2/tokenP`, body, {
            headers: { 'content-type': 'application/json' }
        });

        return NextResponse.json({
            success: true,
            message: "Token Generated Successfully",
            access_token_part: res.data.access_token?.substring(0, 10) + "...",
            expires_in: res.data.expires_in,
            env: {
                key_len: KIS_APP_KEY.length,
                secret_len: KIS_APP_SECRET.length,
                base_url: KIS_BASE_URL,
                tmpdir: os.tmpdir()
            }
        });

    } catch (error: any) {
        return NextResponse.json({
            success: false,
            error: error.message,
            response_data: error.response?.data,
            response_status: error.response?.status,
            env: {
                key_len: KIS_APP_KEY?.length,
                base_url: KIS_BASE_URL
            }
        }, { status: 500 });
    }
}
