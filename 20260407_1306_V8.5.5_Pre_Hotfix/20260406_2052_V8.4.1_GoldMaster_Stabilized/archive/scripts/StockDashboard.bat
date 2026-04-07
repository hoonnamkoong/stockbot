@echo off
title Stock Dashboard Server (Mobile: http://192.168.50.109:3000)
cd dashboard

echo ========================================================
echo [Stock Dashboard Application]
echo.
echo 1. PC Access     : http://localhost:3000
echo 2. Android Access: http://192.168.50.109:3000
echo.
echo * Note: Your PC and Mobile must be on the same Wi-Fi.
echo * Server is starting... Please wait.
echo ========================================================

:: Open Browser automatically
timeout /t 3 >nul
start http://localhost:3000

:: Start Production Server
npm start
