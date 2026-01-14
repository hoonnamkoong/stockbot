import { NextResponse } from 'next/server';
import { fetchReservations, updateReservations } from '@/lib/github-db';

// Dynamic route to prevent caching
export const dynamic = 'force-dynamic';

export async function GET() {
    try {
        const { list } = await fetchReservations();

        // Filter out reservations older than 5 minutes (assumed executed or failed)
        // Actually, with Cron, we might want to keep them until Cron deletes them?
        // But for display, maybe we still hide old ones or show them as 'Processing'?
        // For now, let's keep the view consistent: show future ones.

        const active = list.filter((r: any) => {
            // Show all future or recent past (within 10 mins)
            // If Cron runs every 10 mins, a reservation might 'wait' for 9 mins.
            const cutoff = Date.now() - (15 * 60 * 1000);
            return new Date(r.targetTime).getTime() > cutoff;
        });

        return NextResponse.json({ reservations: active });
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}

export async function DELETE(request: Request) {
    try {
        const { searchParams } = new URL(request.url);
        const id = searchParams.get('id');

        if (!id) return NextResponse.json({ error: "Missing ID" }, { status: 400 });

        // Optimistic update
        const { list, sha } = await fetchReservations();
        const newList = list.filter((r: any) => r.id !== id);

        const success = await updateReservations(newList, `Delete reservation ${id}`, sha);

        if (success) {
            return NextResponse.json({ success: true });
        } else {
            return NextResponse.json({ error: "Failed to update GitHub" }, { status: 500 });
        }
    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}

export async function POST(request: Request) {
    try {
        const body = await request.json();
        const { code, qty, price, hour, minute, side, pin } = body;

        // PIN Verification
        if (pin !== process.env.TRADE_PIN) {
            return NextResponse.json({ error: 'Invalid PIN' }, { status: 401 });
        }

        // Sanitize
        const safeQty = qty ? String(qty) : '1';
        const safePrice = price ? String(price) : '0';
        const safeHour = (hour !== undefined && hour !== '') ? String(hour) : '9';
        const safeMinute = (minute !== undefined && minute !== '') ? String(minute) : '0';

        // Time Validation
        // Time Validation (Fix: Interpret input as KST)
        const now = new Date();
        const kstOffset = 9 * 60 * 60 * 1000;
        const kstNow = new Date(now.getTime() + kstOffset);

        // Construct target time based on KST date components
        const targetKST_Timestamp = Date.UTC(
            kstNow.getUTCFullYear(),
            kstNow.getUTCMonth(),
            kstNow.getUTCDate(),
            Number(safeHour),
            Number(safeMinute),
            0
        );

        // Convert back to true UTC
        const target = new Date(targetKST_Timestamp - kstOffset);

        if (target < now) {
            // Check if it's for tomorrow? For now just reject past time.
            const timeStr = `${safeHour}:${safeMinute}`;
            return NextResponse.json({ error: `Target time (${timeStr}) has passed. Please choose a future time.` }, { status: 400 });
        }

        const newRes = {
            id: Date.now().toString() + Math.random().toString(36).substr(2, 5),
            code,
            qty: safeQty,
            price: safePrice,
            side: side || 'buy',
            targetTime: target.toISOString(),
            createdAt: new Date().toISOString()
        };

        // Save to GitHub
        const { list, sha } = await fetchReservations();
        list.push(newRes);

        const success = await updateReservations(list, `Add reservation for ${code}`, sha);

        if (success) {
            return NextResponse.json({ success: true, message: 'Reservation scheduled (Saved to Cloud)', reservation: newRes });
        } else {
            return NextResponse.json({ error: "Failed to save to Cloud Storage (GitHub)" }, { status: 500 });
        }

    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
