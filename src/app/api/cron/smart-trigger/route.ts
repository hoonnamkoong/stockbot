import { NextResponse } from 'next/server';
import axios from 'axios';
import { fetchReservations } from '@/lib/github-db';

export const dynamic = 'force-dynamic';
export const maxDuration = 60; // Allow up to 60 seconds for long operations

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';
    const WORKFLOW_FILE = 'scraper.yml';

    let executedCount = 0;

    try {
        // Get current KST time
        const now = new Date();
        const kstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000);
        const hour = kstTime.getHours();
        const minute = kstTime.getMinutes();

        console.log(`[Smart Cron] Triggered at ${hour}:${minute.toString().padStart(2, '0')} KST`);

        // 1. Check if scraping time (10:00, 12:00, 15:00)
        // Allow ±1 minute tolerance for Tasker timing variations
        // IMPORTANT: Tasker triggers at 59 min (e.g., 11:59 for 12:00)
        // So we need to check if (hour+1) is in scraping hours when minute=59

        // CHANGED: 13 -> 12 as per user request (Tasker 11:59 -> 12:00 scraping)
        const scrapingHours = [10, 12, 15];
        const effectiveHour = (minute === 59) ? hour + 1 : hour;

        // STRICT DEDUPLICATION: Only trigger at minute 59.
        const isScrapingTime = scrapingHours.includes(effectiveHour) && (minute === 59);

        if (isScrapingTime) {
            // Triggered at X:59 (e.g., 11:59 for 12:00 scraping)
            console.log(`[Smart Cron] Pre-scraping time detected (59 min). Triggering GitHub Actions for ${effectiveHour}:00...`);

            if (GITHUB_PAT) {
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
            } else {
                console.error('[Smart Cron] Missing GITHUB_PAT');
            }
        } else if (scrapingHours.includes(effectiveHour) && minute === 0) {
            console.log(`[Smart Cron] Scraper call at 00 min ignored (Duplicate prevention). System expects 59 min trigger.`);
        }

        // 2. Check for reservations (Robust Time Window Logic)
        console.log(`[Smart Cron] Checking for reservations...`);

        try {
            const { list: reservations } = await fetchReservations();

            const nowTime = new Date().getTime();
            const lookbackWindow = 20 * 60 * 1000; // 20 minutes

            const dueReservations = reservations.filter((r: any) => {
                if (!r.targetTime) return false;

                const targetTimestamp = new Date(r.targetTime).getTime();
                const isDue = targetTimestamp <= nowTime;
                const isRecent = targetTimestamp > (nowTime - lookbackWindow);

                if (isDue && isRecent) {
                    return true;
                }

                if (isDue && !isRecent) {
                    console.log(`[Smart Cron] Found stale reservation ${r.id} (${r.code}) targeted for ${r.targetTime}. Ignoring.`);
                }

                return false;
            });

            if (dueReservations.length > 0) {
                console.log(`[Smart Cron] Found ${dueReservations.length} due reservation(s). Executing...`);

                const baseUrl = process.env.NEXT_PUBLIC_BASE_URL || 'https://stockbot-phi.vercel.app';

                for (const reservation of dueReservations) {
                    try {
                        await axios.post(
                            `${baseUrl}/api/trade/execute-reservation`,
                            { reservationId: reservation.id },
                            { timeout: 10000 }
                        );
                        console.log(`[Smart Cron] Triggered execution for reservation ${reservation.id}`);
                        executedCount++;
                    } catch (error: any) {
                        console.error(`[Smart Cron] Failed to trigger reservation ${reservation.id}:`, error.message);
                    }
                }
            } else {
                console.log(`[Smart Cron] No reservations due at this time.`);
            }
        } catch (dbError: any) {
            console.error(`[Smart Cron] Failed to fetch reservations:`, dbError.message);
        }

        return NextResponse.json({
            success: true,
            time: `${hour}:${minute.toString().padStart(2, '0')} KST`,
            scrapingTriggered: isScrapingTime,
            reservationsExecuted: executedCount
        });

    } catch (error: any) {
        console.error('[Smart Cron] Error:', error.message);
        return NextResponse.json({
            error: 'Smart cron failed',
            details: error.message
        }, { status: 500 });
    }
}
