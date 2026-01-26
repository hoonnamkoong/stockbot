import { NextResponse } from 'next/server';

export async function POST(request: Request) {
    const body = await request.json();
    const { password } = body;
    const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;

    if (!ADMIN_PASSWORD) {
        return NextResponse.json({ error: 'Server misconfigured (Missing ADMIN_PASSWORD)' }, { status: 500 });
    }

    if (password === ADMIN_PASSWORD) {
        const response = NextResponse.json({ success: true });

        // Set a long-lived cookie (1 year) to mark this device as trusted
        response.cookies.set('admin_session', 'trusted-device-token', {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            maxAge: 60 * 60 * 24 * 365, // 1 year
            path: '/',
        });

        return response;
    }

    return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
}
