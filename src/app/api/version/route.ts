export const dynamic = 'force-dynamic';

const APP_VERSION = 'v50-fix-vercel-build';

export async function GET() {
    return Response.json({
        version: APP_VERSION,
        timestamp: new Date().toISOString(),
        env: {
            nodeEnv: process.env.NODE_ENV,
            vercelEnv: process.env.VERCEL_ENV
        }
    });
}
