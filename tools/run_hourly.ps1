# Hourly PC collector: pull, collect (full exchange set), commit, push.
# Registered in Windows Task Scheduler as "CryptoDashboardHourly" (hourly).
# Cloud writes *-cloud.parquet, this writes *-local.parquet - no git conflicts.
Set-Location "C:\01. Coding\Crypto-Dashboard"
git pull --rebase origin main 2>&1 | Out-Null
python -m collectors.hourly
if ($LASTEXITCODE -ne 0) { exit 1 }
git add data/
git -c user.name="collector-pc" -c user.email="kenkwan86@gmail.com" commit -m "data: pc hourly collect" 2>&1 | Out-Null
git pull --rebase origin main 2>&1 | Out-Null
git push origin main 2>&1 | Out-Null
