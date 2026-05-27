@echo off
chcp 65001 >nul
title EMSXView - 重启服务

REM ============================================================
REM   EMSXView 一键重启脚本
REM   双击这个文件即可重启后端 (FastAPI) + 前端 (npm run dev)
REM   通常使用场景：
REM     - 看到的功能/字段与代码不一致
REM     - 修改了 Python 代码后需要让其生效
REM     - 后端无响应或报错
REM ============================================================

cd /d "%~dp0"

echo.
echo  ╔════════════════════════════════════════════════════╗
echo  ║                                                    ║
echo  ║       EMSXView 交易平台 ─ 一键重启服务              ║
echo  ║                                                    ║
echo  ╚════════════════════════════════════════════════════╝
echo.
echo   正在重启 后端 (端口 3000) 与 前端 (端口 5173)...
echo   重启过程会持续 10 ─ 60 秒，请勿关闭此窗口。
echo.
echo  ──────────────────────────────────────────────────────
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\service-manager.ps1" restart -Environment dev
set "RESTART_EXIT=%ERRORLEVEL%"

echo.
echo  ──────────────────────────────────────────────────────

if not "%RESTART_EXIT%"=="0" (
    echo.
    echo   [失败]  重启过程中出现问题，退出码 = %RESTART_EXIT%
    echo            请把上方红色的错误信息截图反馈。
    echo.
    pause
    exit /b %RESTART_EXIT%
)

echo.
echo   [成功]  服务已重启完成。
echo            后端  ^>  http://localhost:3000
echo            前端  ^>  http://localhost:5173
echo.
echo   正在等待前端就绪（最多等待 90 秒，请耐心等待...）
echo.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\service-manager.ps1" wait-frontend -Environment dev
set "WAIT_EXIT=%ERRORLEVEL%"

if not "%WAIT_EXIT%"=="0" (
    echo.
    echo   [警告] 前端服务未在 90 秒内就绪，将尝试打开页面（可能仍为空白）。
    echo.
) else (
    echo.
    echo   [就绪] 前端已就绪，正在打开页面...
    echo.
)

start "" "http://localhost:5173"

echo.
echo   你可以关闭此窗口了。
echo.
timeout /t 5 /nobreak >nul
exit /b 0
