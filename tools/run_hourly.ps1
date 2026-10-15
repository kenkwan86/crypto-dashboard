# Hourly PC collector: collect (full exchange set), commit data only, pull --rebase, push.
# Registered in Windows Task Scheduler as "CryptoDashboardHourly" (hourly).
# The task launches this via `conhost.exe --headless` so no console window appears.
# All output goes to logs/hourly.log instead of a visible terminal.
# Cloud writes *-cloud.parquet, this writes *-local.parquet - no git conflicts.
#
# Every git step is checked. The script exits 1 (the scheduler shows a failure) when
#   - the collector fails,
#   - the working tree has changes outside data/ (sync BLOCKED: nothing is added or committed),
#   - any git step fails (sync FAILED: <step> exit=<code>).
# "=== run ok ===" is written only when every step succeeded.
# logs/sync-status.json records the outcome of every run for the dashboard.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
$log = Join-Path $logDir "hourly.log"
$statusPath = Join-Path $logDir "sync-status.json"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
# Keep the log from growing without bound: trim to the last 5000 lines.
# Read the tail into a variable first; reading and writing the same file in one pipeline loses it.
if ((Test-Path $log) -and ((Get-Item $log).Length -gt 5MB)) {
    $tail = @(Get-Content -LiteralPath $log -Tail 5000)
    Set-Content -LiteralPath $log -Value $tail
}
function Log($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Add-Content $log }

function Write-Status([bool]$ok, $err) {
    $now = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $lastSuccess = $null
    if ($ok) {
        $lastSuccess = $now
    } elseif (Test-Path -LiteralPath $statusPath) {
        try {
            $previous = [System.IO.File]::ReadAllText($statusPath)
            $m = [regex]::Match($previous, '"last_success_utc"\s*:\s*"([^"]+)"')
            if ($m.Success) { $lastSuccess = $m.Groups[1].Value }
        } catch { }
    }
    $body = [ordered]@{
        last_attempt_utc = $now
        last_success_utc = $lastSuccess
        ok               = $ok
        error            = $err
    }
    $json = $body | ConvertTo-Json
    [System.IO.File]::WriteAllText($statusPath, $json, (New-Object System.Text.UTF8Encoding($false)))
}

function Finish([bool]$ok, $err) {
    Write-Status $ok $err
    if ($ok) { Log "=== run ok ==="; exit 0 }
    exit 1
}

function Invoke-Git([string]$step, [string[]]$gitArgs) {
    $lines = & git @gitArgs 2>&1
    $code = $LASTEXITCODE
    foreach ($line in $lines) { Log "git ${step}: $line" }
    return $code
}

function Fail-Sync([string]$step, [int]$code) {
    $message = "sync FAILED: $step exit=$code"
    Log $message
    Finish $false $message
}

$gitId = @("-c", "user.name=collector-pc", "-c", "user.email=kenkwan86@gmail.com")

Log "=== run start ==="

# 1. Is the code tree clean? Lines under data/ do not count.
$porcelain = @(& git status --porcelain 2>$null)
if ($LASTEXITCODE -ne 0) { Fail-Sync "status" $LASTEXITCODE }
$outside = @()
foreach ($line in $porcelain) {
    $text = "$line"
    if ($text.Length -lt 4) { continue }
    $entry = $text.Substring(3)
    foreach ($part in ($entry -split " -> ")) {
        $path = $part.Trim().Trim('"')
        if (-not ($path -like "data/*")) { $outside += $path }
    }
}
$blocked = $outside.Count -gt 0

# 2. Collect. The collected data stays in the working tree even when sync is blocked.
python -m collectors.hourly 2>&1 | Add-Content $log
$collectorExit = $LASTEXITCODE
if ($collectorExit -ne 0) {
    $message = "collector FAILED exit=$collectorExit"
    Log $message
    Finish $false $message
}

if ($blocked) {
    $message = "sync BLOCKED: uncommitted changes outside data/"
    Log $message
    foreach ($path in ($outside | Select-Object -First 10)) { Log "  blocked by: $path" }
    Finish $false $message
}

# 3. Commit data only (pathspec: staged non-data changes can never be included).
$code = Invoke-Git "add" @("add", "--", "data/")
if ($code -ne 0) { Fail-Sync "add" $code }
& git diff --cached --quiet -- data/ 2>$null
$diffCode = $LASTEXITCODE
if ($diffCode -eq 1) {
    $code = Invoke-Git "commit" ($gitId + @("commit", "-m", "data: pc hourly collect", "--", "data/"))
    if ($code -ne 0) { Fail-Sync "commit" $code }
} elseif ($diffCode -ne 0) {
    Fail-Sync "diff" $diffCode
}

# 4. Pull (rebase) then push.
$code = Invoke-Git "pull" ($gitId + @("pull", "--rebase", "origin", "main"))
if ($code -ne 0) {
    $inRebase = $false
    foreach ($name in @("rebase-merge", "rebase-apply")) {
        $gitPath = (& git rev-parse --git-path $name 2>$null)
        if ($gitPath -and (Test-Path -LiteralPath "$gitPath")) { $inRebase = $true }
    }
    if ($inRebase) { Invoke-Git "rebase-abort" @("rebase", "--abort") | Out-Null }
    Fail-Sync "pull" $code
}
$code = Invoke-Git "push" @("push", "origin", "main")
if ($code -ne 0) { Fail-Sync "push" $code }

Finish $true $null
