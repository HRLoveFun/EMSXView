@echo off
chcp 65001 >nul
echo ==========================================
echo EMSXView Trading Tool - Stop Services
echo ==========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Stop services using PowerShell script
powershell -ExecutionPolicy Bypass -File "ops\service-manager.ps1" stop

echo.
echo Press any key to exit...
pause >nul
