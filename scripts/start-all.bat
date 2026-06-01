@echo off
chcp 65001 >nul
echo ==========================================
echo EMSXView Trading Tool - Start Services
echo ==========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Start services using PowerShell script
powershell -ExecutionPolicy Bypass -File "ops\service-manager.ps1" start -Environment dev

echo.
echo Press any key to exit...
pause >nul
