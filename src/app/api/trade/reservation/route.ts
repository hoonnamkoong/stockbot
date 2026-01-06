import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';
import fs from 'fs';

// Dynamic route to prevent caching
export const dynamic = 'force-dynamic';

const DATA_FILE = path.join(process.cwd(), 'data', 'reservations.json');

function getReservations() {
    if (!fs.existsSync(DATA_FILE)) return [];
    try {
        const data = fs.readFileSync(DATA_FILE, 'utf-8');
        return JSON.parse(data);
    } catch (e) {
        return [];
    }
}

function saveReservations(list: any[]) {
    try {
        // Ensure dir exists
        const dir = path.dirname(DATA_FILE);
        if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
        fs.writeFileSync(DATA_FILE, JSON.stringify(list, null, 2));
    } catch (e) {
        console.error("Failed to save reservations", e);
    }
}

export async function GET() {
    try {
        const list = getReservations();
        // Filter out obviously passed ones? 
        // Or let frontend handle it. Let's return all for now or maybe cleanup old ones.
        // Cleanup expired ones (> 24 hours?)
        const now = Date.now();
        const active = list.filter((r: any) => {
            // Check if active: simpler to just keep them until user deletes or we implement automated cleanup
            // For now, return all. User can clear list.
            return true;
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

        const list = getReservations();
        const target = list.find((r: any) => r.id === id);

        if (target) {
            // Kill Process
            try {
                process.kill(target.pid);
                console.log(`Killed process ${target.pid} for reservation ${id}`);
            } catch (e) {
                console.log(`Process ${target.pid} already dead or not found.`);
            }
        }

        const newList = list.filter((r: any) => r.id !== id);
        saveReservations(newList);

        return NextResponse.json({ success: true });
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

        // Sanitize numeric inputs to prevent python crash (int('') error)
        const safeQty = qty ? String(qty) : '1';
        const safePrice = price ? String(price) : '0';
        const safeHour = (hour !== undefined && hour !== '') ? String(hour) : '9';
        const safeMinute = (minute !== undefined && minute !== '') ? String(minute) : '0';

        // Time Validation
        const now = new Date();
        const target = new Date();
        target.setHours(Number(safeHour));
        target.setMinutes(Number(safeMinute));
        target.setSeconds(0);
        target.setMilliseconds(0);

        // If target is earlier than now (and not tomorrow), reject or handle logic.
        if (target < now) {
            const timeStr = `${safeHour}:${safeMinute}`;
            return NextResponse.json({ error: `Target time (${timeStr}) has passed. Please choose a future time.` }, { status: 400 });
        }

        // Path to python script
        const scriptPath = path.join(process.cwd(), 'trade', 'reservation_order.py');
        const logPath = path.join(process.cwd(), 'trade', 'reservation_spawn.log');

        // Open log file for append
        const logFile = fs.openSync(logPath, 'a');

        // Spawn Background Process with logging
        const subprocess = spawn('python', [
            scriptPath,
            code,
            safeQty,
            safePrice,
            safeHour,
            safeMinute,
            side || 'buy'
        ], {
            detached: true,
            stdio: ['ignore', logFile, logFile], // Redirect stdout/stderr to log
            cwd: path.join(process.cwd(), 'trade') // Set correct CWD for python imports
        });

        subprocess.unref();

        // Save to Reservations List
        const newList = getReservations();
        const newRes = {
            id: Date.now().toString() + Math.random().toString(36).substr(2, 5),
            pid: subprocess.pid,
            code,
            qty: safeQty,
            price: safePrice,
            side: side || 'buy',
            targetTime: target.toISOString(),
            createdAt: new Date().toISOString()
        };
        newList.push(newRes);
        saveReservations(newList);

        return NextResponse.json({ success: true, message: 'Reservation scheduled', reservation: newRes });

    } catch (error: any) {
        return NextResponse.json({ error: error.message }, { status: 500 });
    }
}
