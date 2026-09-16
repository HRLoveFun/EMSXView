# EMSXView Backend Launcher - No Docker, no admin required
# Usage: powershell -File .\start-backend.ps1

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$env:PYTHONPATH = $ProjectRoot

$envFile = Join-Path $ProjectRoot "backend\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([^#][^=]*)=(.*)$') {
            $key   = $Matches[1].Trim()
            $value = $Matches[2].Trim().Trim('"')
            [System.Environment]::SetEnvironmentVariable($key, $value, 'Process')
        }
    }
    Write-Host "Loaded config from .env" -ForegroundColor Green
} else {
    Write-Host "WARNING: .env not found, using defaults" -ForegroundColor Yellow
    $env:BLOOMBERG_HOST   = "localhost"
    $env:BLOOMBERG_PORT   = "8194"
    $env:API_PORT         = "3000"
    $env:API_WORKERS      = "1"
}

# JWT_SECRET 必须显式提供：禁止脚本内回退到硬编码密钥（P1-1 整改）
if (-not $env:JWT_SECRET) {
    Write-Host "ERROR: JWT_SECRET is not set." -ForegroundColor Red
    Write-Host 'Add "JWT_SECRET=<hex>" to backend\.env (or environment), then retry.' -ForegroundColor Red
    Write-Host 'Generate a secure key: python -c "import secrets; print(secrets.token_hex(32))"' -ForegroundColor Red
    exit 1
}

# 监听地址：默认仅本机回环，需对外时通过 API_HOST 环境变量显式放开（P1-1 整改）
$listenHost = if ($env:API_HOST) { $env:API_HOST } else { "127.0.0.1" }

# Clean up old log files before starting
& (Join-Path $PSScriptRoot "..\ops\cleanup-logs.ps1") -Force

# Ensure logs directory exists and capture backend output
$logDir = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "backend-startup.log"

Write-Host "Starting EMSXView Backend on http://localhost:3000 ..." -ForegroundColor Cyan
Write-Host "Log: $logFile" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

$BackendDir = Join-Path $ProjectRoot "backend\api"
Set-Location $BackendDir

# Capture output to log file for error diagnosis
python -m uvicorn main:app --host $listenHost --port 3000 --app-dir $BackendDir *> $logFile
