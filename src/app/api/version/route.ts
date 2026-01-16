export const dynamic = 'force-dynamic';

export async function GET() {
    return Response.json({
        version: 'v29-dynamic-version',
        timestamp: new Date().toISOString(),
        env: {
            nodeEnv: process.env.NODE_ENV,
            hasKey: !!process.env.KIS_APP_KEY
        }
    });
}
