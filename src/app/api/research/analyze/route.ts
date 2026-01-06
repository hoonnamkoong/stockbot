import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';

export async function GET(request: Request) {
    const { searchParams } = new URL(request.url);
    const days = searchParams.get('days') || '5';

    const scriptPath = path.join(process.cwd(), 'src', 'analyzer_5days.py');
    const pythonProcess = spawn('python', [
        scriptPath,
        '--days', days,
        '--json'
    ]);

    let dataString = '';
    let errorString = '';

    return new Promise((resolve) => {
        pythonProcess.stdout.on('data', (data) => {
            dataString += data.toString();
        });

        pythonProcess.stderr.on('data', (data) => {
            errorString += data.toString();
        });

        pythonProcess.on('close', (code) => {
            if (code !== 0) {
                console.error(`Python script exited with code ${code}`);
                console.error(`Stderr: ${errorString}`);
                resolve(NextResponse.json({ error: 'Analysis failed', details: errorString }, { status: 500 }));
            } else {
                try {
                    // Extract JSON part if there is mixed output (though script tries to only print JSON)
                    // The script prints ONLY JSON when --json is passed, but just in case of environment noise:
                    const jsonStart = dataString.indexOf('[');
                    const jsonEnd = dataString.lastIndexOf(']');
                    if (jsonStart !== -1 && jsonEnd !== -1) {
                        const jsonPart = dataString.substring(jsonStart, jsonEnd + 1);
                        const data = JSON.parse(jsonPart);
                        resolve(NextResponse.json({ success: true, data }));
                    } else {
                        // Maybe empty array or error
                        if (dataString.trim() === "[]") {
                            resolve(NextResponse.json({ success: true, data: [] }));
                        } else {
                            console.warn("Invalid JSON output:", dataString);
                            resolve(NextResponse.json({ error: 'Invalid output format' }, { status: 500 }));
                        }
                    }
                } catch (e) {
                    console.error("JSON Parse Error:", e);
                    resolve(NextResponse.json({ error: 'JSON Parse Error' }, { status: 500 }));
                }
            }
        });
    });
}
