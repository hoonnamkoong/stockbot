import { NextResponse } from 'next/server';
import axios from 'axios';

export const dynamic = 'force-dynamic';

export async function GET() {
    const results = {
        kis: { status: 'pending', message: '', details: {} },
        env: {
            hasKisAppKey: !!process.env.KIS_APP_KEY,
            hasKisAppSecret: !!process.env.KIS_APP_SECRET,
            hasKisAccNo: !!process.env.KIS_ACCOUNT_NO,
            kisBaseUrl: process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:443'
        }
    };

    // 1. Test Environment Variables
    if (!results.env.hasKisAppKey || !results.env.hasKisAppSecret) {
        results.kis.status = 'error';
        results.kis.message = 'KIS_APP_KEY 또는 KIS_APP_SECRET 환경변수가 누락되었습니다.';
        return NextResponse.json(results);
    }

    // 2. Test KIS Connection (Direct Token Check)
    try {
        const kisBase = process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:9443';
        const res = await axios.post(`${kisBase}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: (process.env.KIS_APP_KEY || '').trim(),
            appsecret: (process.env.KIS_APP_SECRET || '').trim()
        }, {
            headers: { 'Content-Type': 'application/json' },
            timeout: 5000
        });

        if (res.data.access_token) {
            results.kis.status = 'ok';
            results.kis.message = 'KIS Token API 접속 성공: 서버에서 한국투자증권으로 직접 연결되어 있습니다. (Direct Mode)';
        } else {
            results.kis.status = 'warning';
            results.kis.message = 'KIS 서버 응답은 있으나 토큰이 누락되었습니다.';
        }
    } catch (e: any) {
        const isAuthError = e.response?.status === 403 || e.response?.status === 401;
        results.kis.status = 'error';
        results.kis.message = `KIS 연결 실패: ${e.message}. ${isAuthError ? 'APP_KEY/SECRET을 확인해주세요.' : '네트워크 환경을 확인해주세요.'}`;
    }

    return NextResponse.json(results);
}
