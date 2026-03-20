# EMSX Backend Launcher - 无需 Docker，无需管理员权限
# 运行方式：在 PowerShell 中执行  .\start-backend.ps1

$env:PATH = "D:\anaconda3\Scripts;D:\anaconda3\Library\bin;" + $env:PATH

# 从 .env 文件加载配置
$envFile = "C:\Users\hrchen\Documents\EMSX\emsx-backend\.env"
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

# Ensure log directory exists (now using project root logs/)
New-Item -ItemType Directory -Force -Path "C:\Users\hrchen\Documents\EMSX\logs" | Out-Null

Write-Host "Starting EMSX Backend on http://localhost:3000 ..." -ForegroundColor Cyan
Write-Host "Logs: C:\Users\hrchen\Documents\EMSX\logs" -ForegroundColor Gray
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

# Change to backend directory so Python runs from correct location
$BackendDir = "C:\Users\hrchen\Documents\EMSX\emsx-backend\backend"
Set-Location $BackendDir

D:\anaconda3\python.exe -m uvicorn main:app `
    --host 0.0.0.0 `
    --port 3000 `
    --app-dir $BackendDir
