@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================================
REM   EMSXView 服务管理统一入口（2026-10-27 合并原 scripts/*-all.bat）
REM   用法: emsxview.bat [start^|stop^|restart^|status]
REM     不带参数默认 status；退出码透传自 service-manager.ps1
REM ============================================================

set "ROOT=%~dp0"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=status"

if /I "%ACTION%"=="start" goto :run
if /I "%ACTION%"=="stop" goto :run
if /I "%ACTION%"=="restart" goto :run
if /I "%ACTION%"=="status" goto :run

echo [错误] 未知操作: %ACTION%
echo 用法: emsxview.bat [start^|stop^|restart^|status]
exit /b 2

:run
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%scripts\ops\service-manager.ps1" %ACTION% -Environment dev
set "EXIT_CODE=%ERRORLEVEL%"
exit /b %EXIT_CODE%
