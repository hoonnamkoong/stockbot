
@echo off
echo Starting Stock Dashboard...
cd dashboard

:: Install dependencies if node_modules missing
if not exist node_modules (
    echo Installing dependencies...
    call npm install
)

:: Start Scheduler in background
echo Starting Scheduler...
start /b node scheduler.js

:: Start Next.js App
echo Starting Web Dashboard...
echo Opening browser...
start http://localhost:3000
call npm run dev
