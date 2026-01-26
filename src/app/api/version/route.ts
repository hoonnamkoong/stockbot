export const dynamic = 'force-dynamic';

export const VERSION = 'v46-device-whitelist';

export async function GET() {
    return Response.json({
        version: VERSION,
        timestamp: new Date().toISOString(),
        env: {
            nodeEnv: process.env.NODE_ENV,
            vercelEnv: process.env.VERCEL_ENV
        }
    });
}
