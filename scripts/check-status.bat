@echo off
chcp 65001 >nul
echo ==========================================
echo EMSX Trading Tool - Service Status
echo ==========================================
echo.

REM Change to script directory
cd /d "%~dp0"

REM Check status using PowerShell script
powershell -ExecutionPolicy Bypass -File "service-manager.ps1" status

echo.
pause
