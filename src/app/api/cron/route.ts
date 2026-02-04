import { NextResponse } from 'next/server';
import axios from 'axios';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

export async function GET(request: Request) {
    const GITHUB_PAT = process.env.GITHUB_PAT;
    const REPO_OWNER = 'hoonnamkoong';
    const REPO_NAME = 'stockbot';
    const WORKFLOW_FILE = 'scraper.yml';

    try {
        // Parse debug params
        const { searchParams } = new URL(request.url);
        const debugHour = searchParams.get('hour');
        const debugMinute = searchParams.get('minute');

        // Get current KST time
        const now = new Date();
        const kstTime = new Date(now.getTime() + 9 * 60 * 60 * 1000);

        // Use debug time if provided, otherwise use real time
        let hour = debugHour ? parseInt(debugHour) : kstTime.getHours();
        let minute = debugMinute ? parseInt(debugMinute) : kstTime.getMinutes();
        const dayOfWeek = kstTime.getDay(); // 0=Sun, 6=Sat

        // Allow debug to bypass current time for logs
        if (debugHour) {
            console.log(`[Debug] Simulating time: ${hour}:${minute} (Real: ${kstTime.getHours()}:${kstTime.getMinutes()})`);
        } else {
            console.log(`[Cron] Triggered at ${hour}:${minute.toString().padStart(2, '0')} KST (Day: ${dayOfWeek})`);
        }

        // 0. Check if market is open (Mon-Fri only)
        if (dayOfWeek === 0 || dayOfWeek === 6) {
            const dayName = dayOfWeek === 0 ? 'Sunday' : 'Saturday';
            console.log(`[Cron] Market closed (${dayName}). Skipping execution.`);
            return NextResponse.json({
                success: true,
                skipped: true,
                reason: `Market closed on ${dayName}`,
                time: `${hour}:${minute.toString().padStart(2, '0')} KST`
            });
        }

        // 1. Check if scraping time (handles both X:59 and X:00 triggers)
        const scrapingHours = [10, 13, 15];
        const isScrapingTime =
            (scrapingHours.includes(hour) && minute === 0) ||           // X:00 trigger
            (scrapingHours.includes(hour + 1) && minute === 59);        // X:59 trigger (for next hour)

        if (isScrapingTime) {
            console.log(`[Cron] Scraping time detected (${hour}:${minute.toString().padStart(2, '0')} KST). Triggering GitHub Actions...`);

            if (!GITHUB_PAT) {
                console.error('[Cron] GITHUB_PAT is missing!');
                return NextResponse.json({
                    error: 'Missing GITHUB_PAT',
                    success: false
                }, { status: 500 });
            }

            try {
                const response = await axios.post(
                    `https://api.github.com/repos/${REPO_OWNER}/${REPO_NAME}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
                    { ref: 'main' },
                    {
                        headers: {
                            Authorization: `Bearer ${GITHUB_PAT}`,
                            Accept: 'application/vnd.github.v3+json',
                        },
                    }
                );

                console.log(`[Cron] GitHub Actions triggered successfully. Status: ${response.status}`);
            } catch (githubError: any) {
                console.error('[Cron] GitHub API Error:', githubError.message);
                console.error('[Cron] Error details:', githubError.response?.data);

                return NextResponse.json({
                    error: 'Failed to trigger GitHub Actions',
                    details: githubError.message,
                    githubResponse: githubError.response?.data,
                    success: false
                }, { status: 500 });
            }
        }

        return NextResponse.json({
            success: true,
            time: `${hour}:${minute.toString().padStart(2, '0')} KST`,
            scrapingTriggered: isScrapingTime
        });

    } catch (error: any) {
        console.error('[Cron] Error:', error.message);
        return NextResponse.json({
            error: 'Cron execution failed',
            details: error.message
        }, { status: 500 });
    }
}
