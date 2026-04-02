import { NextResponse } from 'next/server';
import axios from 'axios';
import { fetchFile } from '@/lib/github-db';

export const dynamic = 'force-dynamic';

export async function GET() {
    const results = {
        github: { status: 'pending', message: '', details: {} },
        kis: { status: 'pending', message: '', details: {} },
        env: {
            hasGithubPat: !!process.env.GITHUB_PAT,
            hasKisAppKey: !!process.env.KIS_APP_KEY,
            hasKisAppSecret: !!process.env.KIS_APP_SECRET,
            hasKisAccNo: !!process.env.KIS_ACCOUNT_NO,
            kisBaseUrl: process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:443'
        }
    };

    // 1. Test GitHub Connection
    try {
        // Try to fetch a known file or just repo info
        const { sha } = await fetchFile('data/status.json');
        if (sha) {
            results.github.status = 'ok';
            results.github.message = 'Successfully connected to GitHub and retrieved file info.';
        } else {
            results.github.status = 'warning';
            results.github.message = 'Connected to GitHub, but status.json not found (might be normal for new setup).';
        }
    } catch (e: any) {
        results.github.status = 'error';
        results.github.message = `GitHub Connection Failed: ${e.message}`;
        results.github.details = {
            status: e.response?.status,
            data: e.response?.data
        };
    }

    // 2. Test KIS Connection (Basic Health Check / Token Server)
    try {
        const kisBase = process.env.KIS_BASE_URL || 'https://openapi.koreainvestment.com:443';
        // We just check if the server is reachable by calling a simple endpoint or just pinging
        // Note: Real token request might fail due to IP restrictions, which is useful information!
        const res = await axios.post(`${kisBase}/oauth2/tokenP`, {
            grant_type: 'client_credentials',
            appkey: (process.env.KIS_APP_KEY || '').trim(),
            appsecret: (process.env.KIS_APP_SECRET || '').trim()
        }, {
            headers: {
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            },
            timeout: 7000
        });

        if (res.data.access_token) {
            results.kis.status = 'ok';
            results.kis.message = 'KIS Token API responded successfully (Direct server-to-server connection OK).';
        } else {
            results.kis.status = 'warning';
            results.kis.message = 'KIS responded but access_token is missing.';
        }
    } catch (e: any) {
        if (e.response?.status === 403 || e.code === 'ECONNREFUSED' || e.code === 'ETIMEDOUT') {
            results.kis.status = 'blocked';
            results.kis.message = `KIS Connection Blocked/Failed: ${e.message}. This is likely due to Vercel IP blocking. Mobile Agent should handle this instead.`;
        } else {
            results.kis.status = 'error';
            results.kis.message = `KIS Connection Error: ${e.message}`;
        }
        results.kis.details = {
            status: e.response?.status,
            data: e.response?.data,
            code: e.code
        };
    }

    return NextResponse.json(results);
}
