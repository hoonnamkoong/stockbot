@echo off
title Stock Dashboard Mobile Launcher (LTE/5G)
cd dashboard

echo ========================================================
echo [Stock Dashboard - External Access Mode]
echo.
echo 1. Server is starting...
echo 2. A separate 'ngrok' window will open.
echo 3. In the ngrok window, find 'Forwarding':
echo    Example: https://xxxx-xxxx.ngrok-free.app
echo.
echo 4. Enter that URL in your mobile browser.
echo ========================================================

:: Open ngrok in a separate window
start ngrok http 3000

:: Open Local Browser
timeout /t 5 >nul
start http://localhost:3000

:: Start Server
npm start
