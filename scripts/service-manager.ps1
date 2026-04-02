#!/usr/bin/env powershell
<#
.SYNOPSIS
    EMSX Trading Tool - Service Manager
    Manages backend and frontend services with synchronized startup/shutdown

.DESCRIPTION
    This script provides comprehensive service management for the EMSX Trading Tool:
    - Start/Stop/Restart backend and frontend services
    - Port conflict detection and resolution
    - Health checks and connection validation
    - Synchronized startup (backend starts first, then frontend)
    - Graceful shutdown with cleanup

.PARAMETER Action
    The action to perform: start, stop, restart, status, logs

.PARAMETER Environment
    The environment to run: dev (default) or prod

.EXAMPLE
    .\service-manager.ps1 start
    Starts both backend and frontend services

.EXAMPLE
    .\service-manager.ps1 restart -Environment prod
    Restarts services in production mode

.EXAMPLE
    .\service-manager.ps1 status
    Shows current service status
#>

param(
    [Parameter(Position=0)]
    [ValidateSet("start", "stop", "restart", "status", "logs", "kill")]
    [string]$Action = "status",

    [Parameter()]
    [ValidateSet("dev", "prod")]
    [string]$Environment = "dev",

    [Parameter()]
    [switch]$VerboseOutput
)

# Configuration
$Config = @{
    ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
    Backend = @{
        Port = 3000
        Script = "Execution\backend\api\start_server.py"
        ProcessName = "python"
        HealthUrl = "http://localhost:3000/health"
        StartupDelay = 3
    }
    Frontend = @{
        DevPort = 5173
        ProdPort = 80
        DevScript = "npm run dev"
        ProdScript = "npm run preview"
        ProcessName = "node"
        StartupDelay = 5
    }
    LogDir = "logs"
}

# Colors for output
$Colors = @{
    Success = "Green"
    Error = "Red"
    Warning = "Yellow"
    Info = "Cyan"
    Normal = "White"
}

# Helper Functions
function Write-Status {
    param([string]$Message, [string]$Level = "Info")
    $color = $Colors[$Level]
    Write-Host "[$Level] $Message" -ForegroundColor $color
}

function Write-Separator {
    Write-Host "-" * 60 -ForegroundColor DarkGray
}

function Test-PortInUse {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Get-ProcessUsingPort {
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connection) {
        return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    }
    return $null
}

function Test-BackendHealth {
    try {
        $response = Invoke-WebRequest -Uri $Config.Backend.HealthUrl -Method GET -TimeoutSec 2 -ErrorAction SilentlyContinue
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Get-ServiceStatus {
    $backendProcess = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*start_server.py*" -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*main:app*")
    } | Select-Object -First 1

    $frontendProcess = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*vite*" -and $_.CommandLine -like "*Execution\frontend*"
    } | Select-Object -First 1

    $backendPortInUse = Test-PortInUse -Port $Config.Backend.Port
    $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }
    $frontendPortInUse = Test-PortInUse -Port $frontendPort

    return @{
        Backend = @{
            Running = $null -ne $backendProcess
            PortInUse = $backendPortInUse
            Process = $backendProcess
            Healthy = if ($backendPortInUse) { Test-BackendHealth } else { $false }
        }
        Frontend = @{
            Running = $null -ne $frontendProcess
            PortInUse = $frontendPortInUse
            Process = $frontendProcess
        }
    }
}

function Stop-BackendService {
    Write-Status "Stopping backend service..." "Info"

    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*start_server.py*" -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*main:app*")
    }

    foreach ($proc in $processes) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Status "Stopped Python process (PID: $($proc.ProcessId))" "Success"
        }
        catch {
            Write-Status "Failed to stop process $($proc.ProcessId): $($_.Exception.Message)" "Error"
        }
    }

    $retryCount = 0
    while ((Test-PortInUse -Port $Config.Backend.Port) -and $retryCount -lt 10) {
        Write-Status "Waiting for port $($Config.Backend.Port) to be released..." "Warning"
        Start-Sleep -Milliseconds 500
        $retryCount++
    }

    if (Test-PortInUse -Port $Config.Backend.Port) {
        $proc = Get-ProcessUsingPort -Port $Config.Backend.Port
        if ($proc) {
            Write-Status "Force killing process using port $($Config.Backend.Port) (PID: $($proc.Id))" "Warning"
            Stop-Process -Id $proc.Id -Force
        }
    }

    Write-Status "Backend service stopped" "Success"
}

function Stop-FrontendService {
    Write-Status "Stopping frontend service..." "Info"

    $processes = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*vite*" -and $_.CommandLine -like "*Execution\frontend*"
    }

    foreach ($proc in $processes) {
        try {
            Stop-Process -Id $proc.ProcessId -Force -ErrorAction Stop
            Write-Status "Stopped Node process (PID: $($proc.ProcessId))" "Success"
        }
        catch {
            Write-Status "Failed to stop process $($proc.ProcessId): $($_.Exception.Message)" "Error"
        }
    }

    Get-Process | Where-Object { $_.ProcessName -eq "node" } | ForEach-Object {
        try {
            $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)"
            if ($procInfo.CommandLine -like "*Execution\frontend*") {
                Stop-Process -Id $_.Id -Force
                Write-Status "Stopped Node process (PID: $($_.Id))" "Success"
            }
        }
        catch {
            # Ignore errors
        }
    }

    Write-Status "Frontend service stopped" "Success"
}

function Start-BackendService {
    Write-Status "Starting backend service..." "Info"

    if (Test-PortInUse -Port $Config.Backend.Port) {
        $proc = Get-ProcessUsingPort -Port $Config.Backend.Port
        Write-Status "Port $($Config.Backend.Port) is already in use by process: $($proc.ProcessName) (PID: $($proc.Id))" "Error"
        Write-Status "Please stop the existing service first or use 'restart' action" "Warning"
        return $false
    }

    $logDir = Join-Path $Config.ProjectRoot $Config.LogDir
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    $backendScript = Join-Path $Config.ProjectRoot $Config.Backend.Script
    $logFile = Join-Path $logDir "backend-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

    Write-Status "Starting backend (log: $logFile)..." "Info"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "python"
    $startInfo.Arguments = "`"$backendScript`""
    $startInfo.WorkingDirectory = Split-Path $backendScript -Parent
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)

    Write-Status "Waiting for backend to start (up to $($Config.Backend.StartupDelay) seconds)..." "Info"
    $attempts = 0
    $started = $false

    while ($attempts -lt ($Config.Backend.StartupDelay * 2)) {
        Start-Sleep -Milliseconds 500

        if (Test-BackendHealth) {
            $started = $true
            break
        }

        if ($process.HasExited) {
            Write-Status "Backend process exited unexpectedly!" "Error"
            return $false
        }

        $attempts++
    }

    if ($started) {
        Write-Status "Backend started successfully on port $($Config.Backend.Port)" "Success"
        return $true
    }
    else {
        Write-Status "Backend failed to start within expected time" "Warning"
        Write-Status "Process may still be starting - check logs at $logFile" "Warning"
        return $false
    }
}

function Start-FrontendService {
    param([bool]$WaitForBackend = $true)

    Write-Status "Starting frontend service ($Environment mode)..." "Info"

    $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }

    if ($WaitForBackend -and -not (Test-BackendHealth)) {
        Write-Status "Backend is not ready. Waiting..." "Warning"
        $attempts = 0
        while ($attempts -lt 10 -and -not (Test-BackendHealth)) {
            Start-Sleep -Seconds 1
            $attempts++
        }

        if (-not (Test-BackendHealth)) {
            Write-Status "Backend is not responding. Frontend may have connection issues." "Warning"
        }
    }

    if (Test-PortInUse -Port $frontendPort) {
        $proc = Get-ProcessUsingPort -Port $frontendPort
        Write-Status "Port $frontendPort is already in use by process: $($proc.ProcessName) (PID: $($proc.Id))" "Error"
        return $false
    }

    $frontendDir = Join-Path $Config.ProjectRoot "Execution\frontend"
    $logDir = Join-Path $Config.ProjectRoot $Config.LogDir
    $logFile = Join-Path $logDir "frontend-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    $script = if ($Environment -eq "dev") { $Config.Frontend.DevScript } else { $Config.Frontend.ProdScript }

    Write-Status "Starting frontend (log: $logFile)..." "Info"

    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "powershell"
    $startInfo.Arguments = "-Command `"cd '$frontendDir'; $script`""
    $startInfo.WorkingDirectory = $frontendDir
    $startInfo.UseShellExecute = $false
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)

    Write-Status "Waiting for frontend to start (up to $($Config.Frontend.StartupDelay) seconds)..." "Info"
    Start-Sleep -Seconds $Config.Frontend.StartupDelay

    if (-not $process.HasExited) {
        Write-Status "Frontend started successfully on port $frontendPort" "Success"
        Write-Status "Access URL: http://localhost:$frontendPort" "Info"
        return $true
    }
    else {
        Write-Status "Frontend process exited unexpectedly!" "Error"
        return $false
    }
}

function Show-ServiceStatus {
    Write-Separator
    Write-Status "Service Status Check" "Info"
    Write-Separator

    $status = Get-ServiceStatus

    # Backend Status
    Write-Host "Backend Service: " -NoNewline
    if ($status.Backend.Running) {
        Write-Host "RUNNING" -ForegroundColor Green -NoNewline
        Write-Host " (PID: $($status.Backend.Process.ProcessId))" -ForegroundColor Gray
    }
    else {
        Write-Host "STOPPED" -ForegroundColor Red
    }

    Write-Host "  Port $($Config.Backend.Port): " -NoNewline
    if ($status.Backend.PortInUse) {
        Write-Host "IN USE" -ForegroundColor Green
    }
    else {
        Write-Host "FREE" -ForegroundColor Gray
    }

    Write-Host "  Health Check: " -NoNewline
    if ($status.Backend.Healthy) {
        Write-Host "HEALTHY" -ForegroundColor Green
    }
    else {
        Write-Host "NOT RESPONDING" -ForegroundColor Red
    }

    # Frontend Status
    $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }
    Write-Host "`nFrontend Service: " -NoNewline
    if ($status.Frontend.Running) {
        Write-Host "RUNNING" -ForegroundColor Green -NoNewline
        Write-Host " (PID: $($status.Frontend.Process.ProcessId))" -ForegroundColor Gray
    }
    else {
        Write-Host "STOPPED" -ForegroundColor Red
    }

    Write-Host "  Port $frontendPort`: " -NoNewline
    if ($status.Frontend.PortInUse) {
        Write-Host "IN USE" -ForegroundColor Green
    }
    else {
        Write-Host "FREE" -ForegroundColor Gray
    }

    Write-Separator
}

function Show-Logs {
    $logDir = Join-Path $Config.ProjectRoot $Config.LogDir

    if (-not (Test-Path $logDir)) {
        Write-Status "Log directory not found: $logDir" "Error"
        return
    }

    $logFiles = Get-ChildItem -Path $logDir -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 10

    if ($logFiles.Count -eq 0) {
        Write-Status "No log files found" "Warning"
        return
    }

    Write-Separator
    Write-Status "Recent Log Files" "Info"
    Write-Separator

    $index = 1
    foreach ($file in $logFiles) {
        $size = if ($file.Length -gt 1MB) {
            "{0:N2} MB" -f ($file.Length / 1MB)
        }
        else {
            "{0:N2} KB" -f ($file.Length / 1KB)
        }
        Write-Host "$index. $($file.Name)" -ForegroundColor Cyan -NoNewline
        Write-Host " ($size, $($file.LastWriteTime))" -ForegroundColor Gray
        $index++
    }

    Write-Separator
    Write-Host "Use 'Get-Content <logfile> -Tail 50' to view recent entries" -ForegroundColor Yellow
}

# Main Script Logic
Write-Separator
Write-Status "EMSX Trading Tool - Service Manager" "Info"
Write-Status "Action: $Action | Environment: $Environment" "Info"
Write-Separator

switch ($Action) {
    "start" {
        $backendStarted = Start-BackendService
        if ($backendStarted) {
            Start-FrontendService -WaitForBackend $true
        }
        else {
            Write-Status "Backend failed to start. Frontend will not be started." "Error"
        }
    }
    "stop" {
        Stop-FrontendService
        Stop-BackendService
    }
    "restart" {
        Stop-FrontendService
        Stop-BackendService
        Write-Status "Waiting for services to fully stop..." "Info"
        Start-Sleep -Seconds 2
        $backendStarted = Start-BackendService
        if ($backendStarted) {
            Start-FrontendService -WaitForBackend $true
        }
    }
    "status" {
        Show-ServiceStatus
    }
    "logs" {
        Show-Logs
    }
    "kill" {
        Write-Status "Force killing all related processes..." "Warning"
        Stop-FrontendService
        Stop-BackendService
        Get-Process | Where-Object { $_.ProcessName -in @("python", "python3", "node") } | ForEach-Object {
            try {
                $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)"
                if ($procInfo.CommandLine -like "*EMSX*" -or $procInfo.CommandLine -like "*emsx*") {
                    Stop-Process -Id $_.Id -Force
                    Write-Status "Killed process $($_.ProcessName) (PID: $($_.Id))" "Success"
                }
            }
            catch {
                # Ignore errors
            }
        }
    }
}

Write-Separator
