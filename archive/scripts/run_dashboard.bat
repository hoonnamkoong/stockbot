@echo off
echo Starting Stock Dashboard...

:: Install dependencies if node_modules missing or package.json changed
if not exist node_modules (
    echo Installing dependencies...
    call npm install
)

:: Start Scheduler in background (assuming scheduler.js exists in root or scripts?)
:: Verify where scheduler.js is. Step 764 doesn't show it in root.
:: It might be in 'src' or missed?
:: for now, comment out scheduler if not sure, or assume root.
:: echo Starting Scheduler...
:: start /b node scheduler.js

:: Start Next.js App
echo Starting Web Dashboard...
echo Opening browser...
start http://localhost:3000
call npm run dev
