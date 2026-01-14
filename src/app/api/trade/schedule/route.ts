import { NextResponse } from 'next/server';
import { fetchReservations, updateReservations } from '@/lib/github-db';
import { placeOrder } from '@/lib/kis-api';

// Vercel Cron routes are GET
export const dynamic = 'force-dynamic';

export async function GET(request: Request) {
    // Optional: Verify Vercel Signature if needed for security
    // const authHeader = request.headers.get('authorization');
    // if (authHeader !== `Bearer ${process.env.CRON_SECRET}`) ...

    try {
        console.log("[Scheduler] Checking reservations...");
        const { list, sha } = await fetchReservations();

        if (list.length === 0) {
            return NextResponse.json({ message: "No reservations found" });
        }

        const now = Date.now();
        const results: any[] = [];
        const executedIds: string[] = []; // Still needed for GitHub commit message
        const failedIds: string[] = []; // Still needed for GitHub commit message
        const remainingList: any[] = []; // Still needed for GitHub update

        // Loop through reservations
        for (const res of list) {
            const targetTime = new Date(res.targetTime).getTime();
            const oneDay = 24 * 60 * 60 * 1000;

            if (targetTime > now) {
                // Future
                remainingList.push(res);
                continue;
            }

            if (now - targetTime > oneDay) {
                console.log(`[Scheduler] Skipping stale reservation ${res.id}`);
                continue; // Remove stale
            }

            // Execute
            console.log(`[Scheduler] Executing reservation ${res.id}: ${res.side} ${res.code}`);
            try {
                const output = await placeOrder(res.code, Number(res.qty), Number(res.price), res.side);
                executedIds.push(res.id);
                results.push({ id: res.id, status: 'success', output });
            } catch (e: any) {
                const errorMsg = e.message || "Unknown Error";
                console.error(`[Scheduler] Failed to execute ${res.id}:`, errorMsg);
                failedIds.push(res.id);
                remainingList.push(res); // Keep in list to retry
                results.push({ id: res.id, status: 'failed', error: errorMsg });
            }
        }

        // Update GitHub
        let githubStatus = 'skipped';
        if (executedIds.length > 0 || list.length !== remainingList.length) {
            const success = await updateReservations(remainingList, `Scheduler: Processed ${executedIds.length} orders`, sha);
            githubStatus = success ? 'updated' : 'failed_update';
            if (!success) {
                console.error("[Scheduler] Failed to update GitHub. Executed items might reappear.");
                // Note: If update fails, we might want to alert?
            }
        }

        return NextResponse.json({
            success: true,
            githubStatus,
            results,
            remainingCount: remainingList.length,
            debug: {
                env_url: process.env.KIS_BASE_URL || 'default-vts',
                key_start: (process.env.KIS_APP_KEY || '').substring(0, 4),
                has_secret: !!process.env.KIS_APP_SECRET
            }
        });

    } catch (error: any) {
        console.error("[Scheduler] Error:", error.message);
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
