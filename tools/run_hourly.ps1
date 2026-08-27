# Hourly PC collector: pull, collect (full exchange set), commit, push.
# Registered in Windows Task Scheduler as "CryptoDashboardHourly" (hourly).
# The task launches this via `conhost.exe --headless` so no console window appears.
# All output goes to logs/hourly.log instead of a visible terminal.
# Cloud writes *-cloud.parquet, this writes *-local.parquet - no git conflicts.
Set-Location "C:\01. Coding\Crypto-Dashboard"

$log = "C:\01. Coding\Crypto-Dashboard\logs\hourly.log"
New-Item -ItemType Directory -Path (Split-Path $log) -Force | Out-Null
# Keep the log from growing without bound: trim to the last 5000 lines.
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
    Get-Content $log -Tail 5000 | Set-Content $log
}
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Add-Content $log }

Log "=== run start ==="
git pull --rebase origin main 2>&1 | Add-Content $log
python -m collectors.hourly 2>&1 | Add-Content $log
if ($LASTEXITCODE -ne 0) { Log "collector FAILED exit=$LASTEXITCODE"; exit 1 }
git add data/
git -c user.name="collector-pc" -c user.email="kenkwan86@gmail.com" commit -m "data: pc hourly collect" 2>&1 | Add-Content $log
git pull --rebase origin main 2>&1 | Add-Content $log
git push origin main 2>&1 | Add-Content $log
Log "=== run ok ==="
