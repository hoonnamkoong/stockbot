import { NextResponse } from 'next/server';
import { fetchFile } from '@/lib/github-db';

export const dynamic = 'force-dynamic'; // Prevent caching

export async function GET() {
    try {
        console.log('[OrderStatus API] Polling data/order_status.json');
        
        // Fetch order statuses written by the mobile agent.
        // It's expected to be a dictionary/map of { [odno]: { status: 'PENDING'|'PROCESSING'|'SUCCESS'|'FAILED', msg?: string } }
        const { data } = await fetchFile<Record<string, any>>('data/order_status.json');
        
        return NextResponse.json({
            success: true,
            data: data || {}
        }, { status: 200 });
        
    } catch (error: any) {
        console.error('[OrderStatus API] Exception:', error.message);
        return NextResponse.json({
            success: false,
            error: `Failed to fetch order status: ${error.message}`
        }, { status: 500 });
    }
}
