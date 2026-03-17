@echo off
title GitHub Code Uploader
echo ========================================================
echo [ Easy GitHub Uploader ]
echo.
echo 1. I will prepare your code for upload.
echo 2. You just need to paste the GitHub Repository URL.
echo ========================================================
echo.

:: Initialize Git
if not exist .git (
    echo [1/5] Initializing Git...
    git init
) else (
    echo [1/5] Git already initialized.
)

:: Add Files
echo [2/5] Adding files...
git add .

:: Configure Git Identity (Local)
git config user.email "bot@stock.dashboard"
git config user.name "StockBot"

:: Commit
echo [3/5] Saving changes...
git commit -m "Auto-deploy via StockBot"

:: Branch
git branch -M main

:: Remote URL Input
echo.
echo [4/5] Please PASTE your GitHub Repository URL below.
echo (Example: https://github.com/my-id/my-stock-bot.git)
echo.
set /p REPO_URL="URL: "

:: Add Remote & Push
echo.
echo [5/5] Uploading to %REPO_URL%...
git remote remove origin 2>nul
git remote add origin %REPO_URL%
echo [4.5/5] Checking for remote updates...
:: Abort any stuck rebase first
git rebase --abort 2>nul
:: Pull with rebase, favoring local changes (-X theirs)
git pull --rebase -X theirs origin main || echo [Warning] Pull failed, forcing push...
git push -u origin main

echo.
echo ========================================================
echo [DONE] Upload Complete!
echo You can now go to GitHub Settings to add Secrets.
echo ========================================================
pause
