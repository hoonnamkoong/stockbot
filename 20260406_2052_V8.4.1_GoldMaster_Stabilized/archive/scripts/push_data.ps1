$ErrorActionPreference = "Stop"

Write-Host "Backing up data..."
if (Test-Path "data_backup") { Remove-Item "data_backup" -Recurse -Force }
Copy-Item "data" "data_backup" -Recurse

Write-Host "Switching to db-data..."
git checkout db-data
git pull origin db-data

Write-Host "Restoring data..."
Copy-Item "data_backup\*" "data" -Recurse -Force

Write-Host "Committing and Pushing..."
git config user.name "StockBot"
git config user.email "bot@stockbot.com"
git add data
git commit -m "manual update: content injection"
git push origin db-data

Write-Host "Switching back to main..."
git checkout main
Write-Host "Done!"
