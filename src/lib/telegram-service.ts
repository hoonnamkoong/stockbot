import axios from 'axios';

// Ensure tokens are cleanly fetched
const TELEGRAM_BOT_TOKEN = (process.env.TELEGRAM_BOT_TOKEN || '').replace(/[\r\n\s]+/g, '');
const TELEGRAM_CHAT_ID = (process.env.TELEGRAM_CHAT_ID || '').replace(/[\r\n\s]+/g, '');

export async function sendTelegramCommand(side: 'buy' | 'sell' | 'reserve_buy' | 'reserve_sell' | string, code: string, qty: number, price: number): Promise<boolean> {
    if (!TELEGRAM_BOT_TOKEN || TELEGRAM_BOT_TOKEN.length < 10) {
        throw new Error('[Security Exception] TELEGRAM_BOT_TOKEN is missing or invalid in environment variables.');
    }
    if (!TELEGRAM_CHAT_ID) {
        throw new Error('[Security Exception] TELEGRAM_CHAT_ID is missing in environment variables.');
    }

    try {
        // Tasker-friendly format: /order | BUY | 005930 | 10
        const message = `/order | ${side.toUpperCase()} | ${code} | ${qty} | ${price}`;
        
        const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
        const payload = {
            chat_id: TELEGRAM_CHAT_ID,
            text: message
        };

        const res = await axios.post(url, payload, {
            headers: {
                'Content-Type': 'application/json'
            }
        });

        if (res.status === 200 && res.data.ok) {
            console.log(`[TelegramService] Successfully sent: ${message}`);
            return true;
        } else {
            console.error(`[TelegramService] Failed to send message. HTTP ${res.status}`, res.data);
            return false;
        }
    } catch (error: any) {
        console.error('[TelegramService] Exception during message sending:', error.message);
        return false;
    }
}
