import { NextResponse } from 'next/server';

export async function POST(request: Request) {
    const body = await request.json();
    const { password, deviceId } = body;

    // 1. Password Check
    const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD;
    if (!ADMIN_PASSWORD) {
        return NextResponse.json({ error: 'Server misconfigured (Missing ADMIN_PASSWORD)' }, { status: 500 });
    }
    if (password !== ADMIN_PASSWORD) {
        return NextResponse.json({ error: 'Invalid password' }, { status: 401 });
    }

    // 2. Device Whitelist Check
    const TRUSTED_DEVICES = process.env.TRUSTED_DEVICES || '';

    // Allow if TRUSTED_DEVICES is not set yet? No, user explicitly asked for pre-designation.
    // If not set, strictly deny to ensure security.
    if (!TRUSTED_DEVICES) {
        return NextResponse.json({ error: 'Security Error: TRUSTED_DEVICES not configured on server' }, { status: 403 });
    }

    if (!deviceId || !TRUSTED_DEVICES.includes(deviceId)) {
        return NextResponse.json({ error: 'Device Not Allowed. Please add Device ID to TRUSTED_DEVICES env var.' }, { status: 403 });
    }

    // 3. Success -> Set Session Cookie
    const response = NextResponse.json({ success: true });

    response.cookies.set('admin_session', 'trusted-device-token', {
        httpOnly: true,
        secure: process.env.NODE_ENV === 'production',
        maxAge: 60 * 60 * 24 * 365, // 1 year
        path: '/',
    });

    return response;
}
