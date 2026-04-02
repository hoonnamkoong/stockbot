import { fetchFile } from './github-db';
import { sendTelegramCommand } from './telegram-service';
import { appendCommand } from './github-db';

export interface HoldingsItem {
    name: string;
    qty: number;
    price: number;
    avg_price: number;
    pl_rate: number;
    pl_amount: number;
    code: string;
}

export interface BalanceData {
    deposit: number;
    total_asset: number;
    holdings: HoldingsItem[];
    raw_output2?: any;
    error?: string;
    sync_status?: string;
    last_cached?: string;
}

/**
 * Hybrid Architecture: Fetch balance from GitHub DB instead of direct KIS API
 */
export async function getBalance(): Promise<BalanceData | null> {
    console.log('[HybridAPI] getBalance called (fetching from GitHub DB portfolio.json)');

    try {
        const { data } = await fetchFile<any>('data/portfolio.json', 'main');
        
        if (data && data.output2 && data.output2.length > 0) {
            const output2 = data.output2[0];
            const output1 = data.output1 || [];
            
            const holdings: HoldingsItem[] = output1.map((item: any) => ({
                name: item.prdt_name || item.code || '',
                qty: Number(item.hldg_qty || 0),
                price: Number(item.prpr || 0),
                avg_price: Number(item.pchs_avg_pric || 0),
                pl_rate: Number(item.evlu_pfls_rt || 0),
                pl_amount: Number(item.evlu_pfls_amt || 0),
                code: item.pdno || ''
            }));

            // Calculate DnCA correctly or default to previous day's deposit
            const depositAmount = Number(output2.dnca_tot_amt || output2.prvs_rcdl_excc_amt || 0);
            
            return {
                deposit: depositAmount,
                total_asset: Number(output2.tot_evlu_amt || 0),
                holdings,
                raw_output2: output2,
                sync_status: "ok",
                last_cached: data.timestamp || new Date().toISOString()
            };
        } else {
            // No data implies mobile agent hasn't uploaded synced data yet
            return {
                deposit: 0,
                total_asset: 0,
                holdings: [],
                error: "모바일 동기화 대기 중",
                sync_status: "waiting"
            };
        }
    } catch (e: any) {
        console.error('[HybridAPI] Exception getting balance:', e.message);
        return {
            deposit: 0,
            total_asset: 0,
            holdings: [],
            error: "모바일 동기화 대기 중",
            sync_status: "waiting"
        };
    }
}

/**
 * Hybrid Architecture: Delegate order to Mobile Agent via Telegram instead of direct KIS API
 */
export async function placeOrder(code: string, qty: number, price: number, side: 'buy' | 'sell'): Promise<any> {
    console.log(`[HybridAPI] placeOrder called: ${side} ${code} x ${qty} @ ${price}`);

    // 1. Send signal via Telegram
    const success = await sendTelegramCommand(side, code, qty, price);

    if (!success) {
        console.error('[HybridAPI] Failed to dispatch Telegram command');
        throw new Error("Failed to dispatch Telegram command to mobile agent.");
    }

    // 2. Log to GitHub DB Commands queue
    const commandReq = {
        type: 'ORDER',
        side: side.toUpperCase(),
        code,
        qty,
        price
    };
    await appendCommand(commandReq);

    // Return optimistic success
    return {
        ODNO: `CMD-${Date.now()}`,
        status: "주문 요청 송신됨",
        hybrid_mode: true
    };
}
