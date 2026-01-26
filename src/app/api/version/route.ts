export const dynamic = 'force-dynamic';

export const VERSION = 'v49-fix-trend-persistence';

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
