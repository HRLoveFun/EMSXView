# EMSX Frontend Launcher - 无需 Docker，无需管理员权限
# 运行方式：在 PowerShell 中执行  .\start-frontend.ps1

$env:PATH = "D:\anaconda3\Scripts;D:\anaconda3\Library\bin;" + $env:PATH

# Kill any existing vite dev servers on port 5173 to avoid stale processes
$existingPid = (netstat -ano | Select-String ":5173.*LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -First 1)
if ($existingPid) {
    Write-Host "Stopping existing server on port 5173 (PID $existingPid)..." -ForegroundColor Yellow
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Write-Host "Starting EMSX Frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

Set-Location "C:\Users\hrchen\Documents\EMSX\ExecutionView\frontend"
npm run dev
