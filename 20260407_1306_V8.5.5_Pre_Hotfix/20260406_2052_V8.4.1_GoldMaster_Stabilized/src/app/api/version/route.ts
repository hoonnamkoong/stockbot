export const dynamic = 'force-dynamic';

const VERSION = 'v53-fix-build-error';

export async function GET() {
    return Response.json({
        version: VERSION,
        timestamp: new Date().toISOString(),
        env: {
            nodeEnv: process.env.NODE_ENV,
            hasKey: !!process.env.KIS_APP_KEY
        }
    });
}
