# EMSX Frontend Launcher - 无需 Docker，无需管理员权限
# 运行方式：在 PowerShell 中执行  .\start-frontend.ps1

$env:PATH = "D:\anaconda3\Scripts;D:\anaconda3\Library\bin;" + $env:PATH

Write-Host "Starting EMSX Frontend on http://localhost:5173 ..." -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Yellow

Set-Location "C:\Users\hrchen\Documents\EMSX\app"
npm run dev
