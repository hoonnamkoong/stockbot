export const dynamic = 'force-dynamic';

export const VERSION = 'v45-security-update-start';

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
