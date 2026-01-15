import { NextResponse } from 'next/server';
import axios from 'axios';

export const dynamic = 'force-dynamic';
export const maxDuration = 60; // Allow up to 60 seconds for long operations

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';
    const WORKFLOW_FILE = 'scraper.yml';

    try {
        // Get current KST time
        const now = new Date();
        const kstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000);
        const hour = kstTime.getHours();
        const minute = kstTime.getMinutes();

        console.log(`[Smart Cron] Triggered at ${hour}:${minute.toString().padStart(2, '0')} KST`);

        // 1. Check if scraping time (10:00, 13:00, 15:00)
        const isScrapingTime = minute === 0 && [10, 13, 15].includes(hour);

        if (isScrapingTime) {
            console.log(`[Smart Cron] Scraping time detected. Triggering GitHub Actions...`);

            if (!GITHUB_PAT) {
                return NextResponse.json({ error: 'Missing GITHUB_PAT' }, { status: 500 });
            }

            await axios.post(
                `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
                { ref: 'main' },
                {
                    headers: {
                        Authorization: `Bearer ${GITHUB_PAT}`,
                        Accept: 'application/vnd.github.v3+json',
                    },
                }
            );

            console.log(`[Smart Cron] Scraper triggered successfully.`);
        }

        // 2. Check for reservations at current time
        console.log(`[Smart Cron] Checking for reservations at ${hour}:${minute.toString().padStart(2, '0')}...`);

        const reservationResponse = await axios.get(
            `${process.env.NEXT_PUBLIC_BASE_URL || 'https://stockbot-phi.vercel.app'}/api/trade/schedule`,
            { timeout: 5000 }
        );

        const reservations = reservationResponse.data.reservations || [];
        const dueReservations = reservations.filter((r: any) => {
            const [resHour, resMin] = r.time.split(':').map(Number);
            return resHour === hour && resMin === minute;
        });

        if (dueReservations.length > 0) {
            console.log(`[Smart Cron] Found ${dueReservations.length} due reservation(s). Executing...`);

            for (const reservation of dueReservations) {
                try {
                    await axios.post(
                        `${process.env.NEXT_PUBLIC_BASE_URL || 'https://stockbot-phi.vercel.app'}/api/trade/execute-reservation`,
                        { reservationId: reservation.id },
                        { timeout: 10000 }
                    );
                    console.log(`[Smart Cron] Executed reservation ${reservation.id} for ${reservation.code}`);
                } catch (error: any) {
                    console.error(`[Smart Cron] Failed to execute reservation ${reservation.id}:`, error.message);
                }
            }
        } else {
            console.log(`[Smart Cron] No reservations due at this time.`);
        }

        return NextResponse.json({
            success: true,
            time: `${hour}:${minute.toString().padStart(2, '0')} KST`,
            scrapingTriggered: isScrapingTime,
            reservationsExecuted: dueReservations.length
        });

    } catch (error: any) {
        console.error('[Smart Cron] Error:', error.message);
        return NextResponse.json({
            error: 'Smart cron failed',
            details: error.message
        }, { status: 500 });
    }
}
