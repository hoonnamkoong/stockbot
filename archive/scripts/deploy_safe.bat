@echo off
echo [Deploy] Starting safe deployment process...

:: 1. Save local changes
echo [Deploy] Stashing local changes (just in case)...
git stash

:: 2. Pull latest changes
echo [Deploy] Pulling latest changes from remote...
git pull --rebase origin main
if %errorlevel% neq 0 (
    echo [Deploy] Pull failed! Manual intervention required.
    git stash pop
    pause
    exit /b %errorlevel%
)

:: 3. Restore local changes
echo [Deploy] Restoring local changes...
git stash pop

:: 4. Add and Commit
echo [Deploy] Committing changes...
git add .
set /p commit_msg="Enter commit message: "
git commit -m "%commit_msg%"

:: 5. Push
echo [Deploy] Pushing to remote...
git push origin main

echo [Deploy] Done!
pause
