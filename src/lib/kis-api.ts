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
    console.log('[HybridAPI] getBalance called (fetching from GitHub DB)');

    try {
        const { data } = await fetchFile<BalanceData>('data/account_balance.json');
        
        if (data) {
            return {
                ...data,
                sync_status: "ok"
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
