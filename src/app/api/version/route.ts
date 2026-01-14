export const dynamic = 'force-dynamic';

export async function GET() {
    return Response.json({
        version: 'v3-final-fix-check-1130',
        timestamp: new Date().toISOString(),
        env: {
            nodeEnv: process.env.NODE_ENV,
            hasKey: !!process.env.KIS_APP_KEY
        }
    });
}
