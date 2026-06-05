# EMSXView Backend Launcher - 无需 Docker，无需管理员权限
# 运行方式：在 PowerShell 中执行  .\start-backend.ps1

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
    $env:JWT_SECRET       = "bbgemsxprogramatictrading"
    $env:API_PORT         = "3000"
    $env:API_WORKERS      = "1"
}

# Clean up old log files before starting
& (Join-Path $PSScriptRoot "..\ops\cleanup-logs.ps1") -Force

New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "logs") | Out-Null

Write-Host "Starting EMSXView Backend on http://localhost:3000 ..." -ForegroundColor Cyan
Write-Host "Logs: $ProjectRoot\logs" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

$BackendDir = Join-Path $ProjectRoot "backend\api"
Set-Location $BackendDir

python -m uvicorn main:app `
    --host 0.0.0.0 `
    --port 3000 `
    --app-dir $BackendDir
