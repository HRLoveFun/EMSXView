@echo off
chcp 65001 >nul
title EMSX Trading Tool - Service Manager

REM ==========================================
REM EMSX Trading Tool - Quick Start Script
REM ==========================================

echo.
echo  ███████╗███╗   ███╗███████╗██╗  ██╗
echo  ██╔════╝████╗ ████║██╔════╝╚██╗██╔╝
echo  █████╗  ██╔████╔██║███████╗ ╚███╔╝
echo  ██╔══╝  ██║╚██╔╝██║╚════██║ ██╔██╗
echo  ███████╗██║ ╚═╝ ██║███████║██╔╝ ██╗
echo  ╚══════╝╚═╝     ╚═╝╚══════╝╚═╝  ╚═╝
echo.
echo  Trading Tool Service Manager
echo.
echo ==========================================
echo.

set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:MENU
echo Choose an action:
echo.
echo  [1] Start Services (Backend + Frontend)
echo  [2] Stop Services
echo  [3] Restart Services
echo  [4] Check Status
echo  [5] View Logs
echo  [6] Exit
echo.
set /p choice="Enter choice (1-6): "

if "%choice%"=="1" goto START
if "%choice%"=="2" goto STOP
if "%choice%"=="3" goto RESTART
if "%choice%"=="4" goto STATUS
if "%choice%"=="5" goto LOGS
if "%choice%"=="6" goto EXIT
goto MENU

:START
echo.
echo [INFO] Starting services...
echo.

REM Start Backend
echo [INFO] Starting Backend on port 3000...
start "EMSX Backend" cmd /k "cd /d "%SCRIPT_DIR%ExecutionView\backend\api" && python start_server.py"

REM Wait for backend to initialize
echo [INFO] Waiting for backend to initialize (5 seconds)...
timeout /t 5 /nobreak >nul

REM Check if backend is running
netstat -ano | findstr :3000 >nul
if %errorlevel%==0 (
    echo [SUCCESS] Backend is running on port 3000
) else (
    echo [WARNING] Backend may not have started properly
)

REM Start Frontend
echo.
echo [INFO] Starting Frontend on port 5173...
start "EMSX Frontend" cmd /k "cd /d "%SCRIPT_DIR%ExecutionView\frontend" && npm run dev"

REM Wait for frontend to initialize
echo [INFO] Waiting for frontend to initialize (5 seconds)...
timeout /t 5 /nobreak >nul

REM Check if frontend is running
netstat -ano | findstr :5173 >nul
if %errorlevel%==0 (
    echo [SUCCESS] Frontend is running on port 5173
) else (
    echo [WARNING] Frontend may not have started properly
)

echo.
echo ==========================================
echo [SUCCESS] Services started!
echo.
echo Backend:  http://localhost:3000
echo Frontend: http://localhost:5173
echo.
echo Press any key to return to menu...
pause >nul
goto MENU

:STOP
echo.
echo [INFO] Stopping services...
echo.

REM Stop Node processes (Frontend)
echo [INFO] Stopping Frontend (Node processes)...
taskkill /F /IM node.exe 2>nul
if %errorlevel%==0 (
    echo [SUCCESS] Frontend stopped
) else (
    echo [INFO] No Node processes found
)

REM Stop Python processes (Backend)
echo [INFO] Stopping Backend (Python processes)...
taskkill /F /FI "WINDOWTITLE eq EMSX Backend" 2>nul
taskkill /F /IM python.exe /FI "COMMANDLINE eq *start_server.py*" 2>nul

REM Force kill any remaining processes on ports
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000') do (
    echo [INFO] Killing process on port 3000 (PID: %%a)
    taskkill /F /PID %%a 2>nul
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
    echo [INFO] Killing process on port 5173 (PID: %%a)
    taskkill /F /PID %%a 2>nul
)

echo.
echo [SUCCESS] All services stopped
echo.
pause
goto MENU

:RESTART
echo.
echo [INFO] Restarting services...
echo.
call :STOP
timeout /t 2 /nobreak >nul
call :START
goto MENU

:STATUS
echo.
echo ==========================================
echo Service Status
echo ==========================================
echo.

REM Check Backend
echo Backend Service:
netstat -ano | findstr :3000 >nul
if %errorlevel%==0 (
    echo   Status: RUNNING
echo   Port 3000: IN USE
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :3000') do (
        echo   Process ID: %%a
    )
) else (
    echo   Status: STOPPED
echo   Port 3000: FREE
)

REM Check Frontend
echo.
echo Frontend Service:
netstat -ano | findstr :5173 >nul
if %errorlevel%==0 (
    echo   Status: RUNNING
echo   Port 5173: IN USE
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr :5173') do (
        echo   Process ID: %%a
    )
) else (
    echo   Status: STOPPED
echo   Port 5173: FREE
)

echo.
echo ==========================================
pause
goto MENU

:LOGS
echo.
echo ==========================================
echo Recent Log Files
echo ==========================================
echo.

if exist "%SCRIPT_DIR%logs" (
    dir /b /o-d "%SCRIPT_DIR%logs\*.log" 2>nul | head -10
    if %errorlevel% neq 0 (
        dir /b /o-d "%SCRIPT_DIR%logs\*.log" 2>nul
    )
) else (
    echo No logs directory found
)

echo.
pause
goto MENU

:EXIT
echo.
echo Goodbye!
timeout /t 1 >nul
exit
