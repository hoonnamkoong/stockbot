import { NextResponse } from 'next/server';
import { getRealPortfolio, getVirtualPortfolio } from '@/lib/kis-api';

export const dynamic = 'force-dynamic';
export const revalidate = 0;

export async function GET(
    request: Request,
    { params }: { params: { type: string } }
) {
    try {
        const { type } = params;

        if (type === 'real') {
            const portfolio = await getRealPortfolio();
            return NextResponse.json(portfolio, {
                status: 200,
                headers: {
                    'Cache-Control': 'no-store, max-age=0, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0',
                }
            });
        } else if (type === 'virtual') {
            const portfolio = await getVirtualPortfolio();
            return NextResponse.json(portfolio, {
                status: 200,
                headers: {
                    'Cache-Control': 'no-store, max-age=0, must-revalidate',
                    'Pragma': 'no-cache',
                    'Expires': '0',
                }
            });
        } else {
            return NextResponse.json({ error: 'Invalid portfolio type' }, { status: 400 });
        }
    } catch (error: any) {
        console.error(`[API-Portfolio] Critical handler error:`, error.message);
        return new Response(JSON.stringify({ 
            error: error.message || 'Internal Server Error',
            sync_status: 'error',
            timestamp: new Date().toISOString()
        }), { 
            status: 500,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}
