import { NextResponse } from 'next/server';
import { fetchReservations, updateReservations } from '@/lib/github-db';
import { placeOrder } from '@/lib/kis';

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
        const executedIds: string[] = [];
        const failedIds: string[] = [];
        const remainingList: any[] = [];

        // Loop through reservations
        for (const res of list) {
            const targetTime = new Date(res.targetTime).getTime();

            // Check if time is due (targetTime <= now)
            // Also buffer: don't execute if older than 24 hours (stale)?
            // Let's execute anything passed targetTime that isn't super old (> 1 day)
            const oneDay = 24 * 60 * 60 * 1000;

            if (targetTime <= now) {
                if (now - targetTime > oneDay) {
                    console.log(`[Scheduler] Skipping stale reservation ${res.id} (${res.targetTime})`);
                    // Just remove it or keep it? Remove it.
                    continue;
                }

                console.log(`[Scheduler] Executing reservation ${res.id}: ${res.side} ${res.code} x ${res.qty}`);
                try {
                    await placeOrder(res.code, Number(res.qty), Number(res.price), res.side);
                    executedIds.push(res.id);
                } catch (e: any) {
                    console.error(`[Scheduler] Failed to execute ${res.id}:`, e.message);
                    failedIds.push(res.id);
                    // Keep in list? Or remove?
                    // If it failed due to API error (e.g. market closed), we might want to retry later?
                    // But for simple logic, let's keep it in list if it failed, 
                    // BUT current logic filters by (targetTime <= now), so it will try again next Cron.
                    // To prevent infinite loop on permanent error, we should probably check retry count?
                    // For now, let's keep it (it will retry every 10 mins).
                    remainingList.push(res);
                }
            } else {
                // Future reservation
                remainingList.push(res);
            }
        }

        // If any executed (and thus removed from remainingList), update GitHub
        if (executedIds.length > 0 || list.length !== remainingList.length) {
            // Note: failing items were pushed back to remainingList, so they are kept.
            // Executed items were NOT pushed, so they are removed.
            // Stale items (>1 day) were NOT pushed, so they are removed.

            const success = await updateReservations(remainingList, `Scheduler: Processed ${executedIds.length} orders`, sha);
            if (success) {
                console.log("[Scheduler] GitHub updated successfully.");
            } else {
                console.error("[Scheduler] Failed to update GitHub.");
            }
        }

        return NextResponse.json({
            success: true,
            executed: executedIds,
            failed: failedIds,
            remaining: remainingList.length
        });

    } catch (error: any) {
        console.error("[Scheduler] Error:", error.message);
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
