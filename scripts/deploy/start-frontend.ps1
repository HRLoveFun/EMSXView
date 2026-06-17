# EMSXView Frontend Launcher - No Docker, no admin required
# Usage: powershell -File .\start-frontend.ps1

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

# Kill any existing vite dev servers on port 5173 to avoid stale processes
$existingPid = (netstat -ano | Select-String ":5173.*LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -First 1)
if ($existingPid) {
    Write-Host "Stopping existing server on port 5173 (PID $existingPid)..." -ForegroundColor Yellow
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "Starting EMSXView Frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

# Ensure logs directory exists
$logDir = Join-Path $ProjectRoot "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logFile = Join-Path $logDir "vite-startup.log"

Write-Host "Vite output log: $logFile" -ForegroundColor Gray

Set-Location (Join-Path $ProjectRoot "frontend")

# Clear Vite pre-built cache to prevent stale/corrupted cache from blocking startup
Remove-Item "$ProjectRoot\frontend\node_modules\.vite" -Recurse -Force -ErrorAction SilentlyContinue

# Use PowerShell native *> redirection to capture all streams to log file
# Unlike Start-Process -Wait, this does NOT block on long-running Vite dev server
npm.cmd run dev *> $logFile
