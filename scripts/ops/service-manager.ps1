#!/usr/bin/env powershell
<#
.SYNOPSIS
    EMSXView Trading Tool - Service Manager
    Manages backend and frontend services with synchronized startup/shutdown

.DESCRIPTION
    This script provides comprehensive service management for the EMSXView Trading Tool:
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
    [ValidateSet("start", "stop", "restart", "status", "logs", "kill", "wait-frontend")]
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
        Script = "ExecutionView\backend\api\start_server.py"
        ProcessName = "python"
        HealthUrl = "http://localhost:3000/api/health"
        StartupStatusScript = "scripts\diagnose\check-startup-status.ps1"
        RequestTimeoutSec = 5
        StartupDelay = 30
        StartupPollInterval = 2
    }
    Frontend = @{
        DevPort = 5173
        ProdPort = 80
        DevScript = "npm run dev"
        ProdScript = "npm run preview"
        ProcessName = "node"
        StartupDelay = 30
    }
    LogDir = "logs/service"
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

function Test-PortActiveListen {
    <#
    .SYNOPSIS
        Returns $true only when a process is actively LISTENING on the given port.
        Ignores TIME_WAIT / CLOSE_WAIT / stale orphaned connections.
    #>
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Test-PortHasAnyConnection {
    <#
    .SYNOPSIS
        Returns $true if the port has ANY TCP state (LISTEN, ESTABLISHED, TIME_WAIT, etc.).
        Used to wait for TIME_WAIT to clear before rebinding.
    #>
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    return $null -ne $connection
}

function Wait-PortCompletelyFree {
    <#
    .SYNOPSIS
        Polls until the given port has zero TCP connections of any state.
        Returns $true once free, $false on timeout.
    #>
    param([int]$Port, [int]$MaxWaitSeconds = 60)
    for ($i = 0; $i -lt $MaxWaitSeconds; $i++) {
        if (-not (Test-PortHasAnyConnection -Port $Port)) {
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return (-not (Test-PortHasAnyConnection -Port $Port))
}

function Get-ProcessUsingPortListening {
    <#
    .SYNOPSIS
        Returns the process that is actively LISTENING on the given port.
        Unlike Get-ProcessUsingPort, this correctly ignores stale orphaned connections.
    #>
    param([int]$Port)
    $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($connection) {
        return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    }
    return $null
}

function Test-BackendHealth {
    try {
        $response = Invoke-WebRequest -Uri $Config.Backend.HealthUrl -Method GET -TimeoutSec $Config.Backend.RequestTimeoutSec -ErrorAction SilentlyContinue
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

function Get-BackendStartupSnapshot {
    param(
        [int]$MaxWaitSeconds = 0,
        [switch]$RequireReady
    )

    $scriptPath = Join-Path $Config.ProjectRoot $Config.Backend.StartupStatusScript
    if (-not (Test-Path $scriptPath)) {
        return @{
            Available = $false
            Error = "Startup status script not found: $scriptPath"
            Snapshot = $null
            ExitCode = $null
        }
    }

    $commandArgs = @(
        '-NoProfile',
        '-ExecutionPolicy', 'Bypass',
        '-File', $scriptPath,
        '-BaseUrl', "http://localhost:$($Config.Backend.Port)",
        '-TimeoutSec', [string]$Config.Backend.RequestTimeoutSec,
        '-MaxWaitSeconds', [string]$MaxWaitSeconds,
        '-PollIntervalSeconds', [string]$Config.Backend.StartupPollInterval,
        '-JsonOutput'
    )

    if ($RequireReady) {
        $commandArgs += '-RequireReady'
    }

    $output = & powershell @commandArgs 2>&1
    $exitCode = $LASTEXITCODE
    $rawOutput = ($output | Out-String).Trim()

    if ($exitCode -ne 0) {
        return @{
            Available = $false
            Error = if ($rawOutput) { $rawOutput } else { "startup-status script failed with exit code $exitCode" }
            Snapshot = $null
            ExitCode = $exitCode
        }
    }

    if (-not $rawOutput) {
        return @{
            Available = $false
            Error = 'startup-status script returned no output.'
            Snapshot = $null
            ExitCode = $exitCode
        }
    }

    try {
        $snapshot = $rawOutput | ConvertFrom-Json
        return @{
            Available = $true
            Error = $null
            Snapshot = $snapshot
            ExitCode = $exitCode
        }
    }
    catch {
        return @{
            Available = $false
            Error = "Failed to parse startup-status output: $($_.Exception.Message)"
            Snapshot = $null
            ExitCode = $exitCode
        }
    }
}

function Test-BackendHttpReady {
    $startupResult = Get-BackendStartupSnapshot
    return $startupResult.Available -and [bool]$startupResult.Snapshot.httpReady
}

function Get-ServiceStatus {
    $backendProcess = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*start_server.py*" -or
        ($_.Name -eq "python.exe" -and $_.CommandLine -like "*main:app*")
    } | Select-Object -First 1

    $frontendProcess = Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -like "*vite*" -and $_.CommandLine -like "*ExecutionView\frontend*"
    } | Select-Object -First 1

    $backendPortInUse = Test-PortActiveListen -Port $Config.Backend.Port
    $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }
    $frontendPortInUse = Test-PortActiveListen -Port $frontendPort
    $backendStartup = if ($backendPortInUse) { Get-BackendStartupSnapshot } else { $null }

    return @{
        Backend = @{
            Running = $null -ne $backendProcess
            PortInUse = $backendPortInUse
            Process = $backendProcess
            HttpReady = if ($backendStartup -and $backendStartup.Available) { [bool]$backendStartup.Snapshot.httpReady } else { $false }
            Healthy = if ($backendStartup -and $backendStartup.Available) { [bool]$backendStartup.Snapshot.healthSuccess } else { $false }
            Startup = if ($backendStartup -and $backendStartup.Available) { $backendStartup.Snapshot } else { $null }
            StartupError = if ($backendStartup -and -not $backendStartup.Available) { $backendStartup.Error } else { $null }
        }
        Frontend = @{
            Running = $null -ne $frontendProcess
            PortInUse = $frontendPortInUse
            Process = $frontendProcess
        }
    }
}

function Show-BackendStartupSummary {
    param(
        [hashtable]$BackendStatus,
        [switch]$IncludeHealthLine
    )

    if ($IncludeHealthLine) {
        Write-Host "  Health Check: " -NoNewline
        if ($BackendStatus.Healthy) {
            Write-Host "HEALTHY" -ForegroundColor Green
        }
        else {
            Write-Host "NOT RESPONDING" -ForegroundColor Red
        }
    }

    Write-Host "  HTTP Ready: " -NoNewline
    if ($BackendStatus.HttpReady) {
        Write-Host "READY" -ForegroundColor Green
    }
    else {
        Write-Host "NOT READY" -ForegroundColor Yellow
    }

    if ($BackendStatus.Startup) {
        Write-Host "  Startup Phase: " -NoNewline
        if ($BackendStatus.Startup.ready) {
            Write-Host ($BackendStatus.Startup.phase.ToUpper()) -ForegroundColor Green
        }
        else {
            Write-Host ($BackendStatus.Startup.phase.ToUpper()) -ForegroundColor Yellow
        }

        Write-Host "  Bloomberg: " -NoNewline
        if ($BackendStatus.Startup.bloombergStatus -eq 'connected') {
            Write-Host ($BackendStatus.Startup.bloombergStatus.ToUpper()) -ForegroundColor Green
        }
        else {
            Write-Host ($BackendStatus.Startup.bloombergStatus.ToUpper()) -ForegroundColor Yellow
        }

        Write-Host "  Subscriptions: " -NoNewline
        Write-Host "ordersInit=$($BackendStatus.Startup.ordersInitPaintDone) routesInit=$($BackendStatus.Startup.routesInitPaintDone) orders=$($BackendStatus.Startup.orderCount) routes=$($BackendStatus.Startup.routeCount)" -ForegroundColor Gray

        if ($BackendStatus.Startup.message) {
            Write-Host "  Startup Message: $($BackendStatus.Startup.message)" -ForegroundColor Gray
        }
    }
    elseif ($BackendStatus.StartupError) {
        Write-Host "  Startup Status: " -NoNewline
        Write-Host "UNAVAILABLE" -ForegroundColor Yellow
        Write-Host "  Startup Error: $($BackendStatus.StartupError)" -ForegroundColor Gray
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

    # Wait up to 60s for any stale TIME_WAIT connection to clear
    if (-not (Wait-PortCompletelyFree -Port $Config.Backend.Port -MaxWaitSeconds 60)) {
        Write-Status "Port $($Config.Backend.Port) still has stale connections after 60s timeout." "Warning"
    }

    if (Test-PortActiveListen -Port $Config.Backend.Port) {
        $proc = Get-ProcessUsingPortListening -Port $Config.Backend.Port
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
        $_.CommandLine -like "*vite*" -and $_.CommandLine -like "*ExecutionView\frontend*"
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
            if ($procInfo.CommandLine -like "*ExecutionView\frontend*") {
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

function Clear-OldServiceLogs {
    param([string]$LogDir, [string]$Prefix, [int]$MaxAgeDays = 7, [int]$MaxFiles = 10)
    if (-not (Test-Path $LogDir)) { return }
    $cutoff = (Get-Date).AddDays(-$MaxAgeDays)

    # 删除超出保留天数的文件
    Get-ChildItem -Path $LogDir -Filter "${Prefix}-*.log" -File |
        Where-Object { $_.LastWriteTime -lt $cutoff } |
        Remove-Item -Force -ErrorAction SilentlyContinue

    # 如仍超出最大文件数，删掉最旧的
    $remaining = Get-ChildItem -Path $LogDir -Filter "${Prefix}-*.log" -File |
                 Sort-Object LastWriteTime -Descending
    if ($remaining.Count -gt $MaxFiles) {
        $remaining | Select-Object -Skip $MaxFiles |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }
}

function Start-BackendService {
    Write-Status "Starting backend service..." "Info"

    # First check: is someone actively listening?  If so, bail out early.
    if (Test-PortActiveListen -Port $Config.Backend.Port) {
        $proc = Get-ProcessUsingPortListening -Port $Config.Backend.Port
        Write-Status "Port $($Config.Backend.Port) is already in use by process: $($proc.ProcessName) (PID: $($proc.Id))" "Error"
        Write-Status "Please stop the existing service first or use 'restart' action" "Warning"
        return $false
    }

    # Second check: could be TIME_WAIT from a recently killed process.
    # Wait up to 60s for it to clear.
    if (Test-PortHasAnyConnection -Port $Config.Backend.Port) {
        Write-Status "Port $($Config.Backend.Port) has stale connections (TIME_WAIT). Waiting up to 60s..." "Warning"
        if (-not (Wait-PortCompletelyFree -Port $Config.Backend.Port -MaxWaitSeconds 60)) {
            Write-Status "Port $($Config.Backend.Port) still busy after 60s. Aborting." "Error"
            return $false
        }
        Write-Status "Port $($Config.Backend.Port) is now free." "Success"
    }

    $logDir = Join-Path $Config.ProjectRoot $Config.LogDir
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Clear-OldServiceLogs -LogDir $logDir -Prefix "backend"

    $backendScript = Join-Path $Config.ProjectRoot $Config.Backend.Script
    $logFile = Join-Path $logDir "backend-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"

    Write-Status "Starting backend (log: $logFile)..." "Info"

    # Use cmd.exe to redirect stdout/stderr to the log file.
    # This avoids .NET's redirected pipe buffers which nobody reads —
    # when the 4 KB pipe fills, the child process blocks on Console.Write
    # and can no longer serve HTTP requests, causing the black-screen bug.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "cmd"
    $startInfo.Arguments = "/c python `"$backendScript`" >> `"$logFile`" 2>&1"
    $startInfo.WorkingDirectory = Split-Path $backendScript -Parent
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($startInfo)

    Write-Status "Waiting for backend to start (up to $($Config.Backend.StartupDelay) seconds)..." "Info"
    $elapsed = 0
    $started = $false
    $startupSnapshot = $null
    $startupError = $null

    while ($elapsed -lt $Config.Backend.StartupDelay) {
        Start-Sleep -Milliseconds 500
        $elapsed += 0.5

        $startupResult = Get-BackendStartupSnapshot
        if ($startupResult.Available -and [bool]$startupResult.Snapshot.httpReady) {
            $started = $true
            $startupSnapshot = $startupResult.Snapshot
            break
        }

        if ($startupResult -and -not $startupResult.Available) {
            $startupError = $startupResult.Error
        }

        if ($process.HasExited) {
            Write-Status "Backend process exited unexpectedly!" "Error"
            return $false
        }
    }

    if ($started) {
        Write-Status "Backend HTTP interface is available on port $($Config.Backend.Port)" "Success"
        if ($startupSnapshot.ready) {
            Write-Status "Backend startup phase: ready" "Success"
        }
        else {
            Write-Status "Backend startup phase: $($startupSnapshot.phase)" "Warning"
            if ($startupSnapshot.message) {
                Write-Status $startupSnapshot.message "Info"
            }
        }
        return $true
    }
    else {
        Write-Status "Backend failed to start within expected time" "Warning"
        Write-Status "Process may still be starting - check logs at $logFile" "Warning"
        if ($startupError) {
            Write-Status $startupError "Warning"
        }
        return $false
    }
}

function Start-FrontendService {
    param([bool]$WaitForBackend = $true)

    Write-Status "Starting frontend service ($Environment mode)..." "Info"

    $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }

    if ($WaitForBackend -and -not (Test-BackendHttpReady)) {
        Write-Status "Backend HTTP interface is not ready yet. Waiting..." "Warning"
        $attempts = 0
        while ($attempts -lt 10 -and -not (Test-BackendHttpReady)) {
            Start-Sleep -Seconds 1
            $attempts++
        }

        if (-not (Test-BackendHttpReady)) {
            Write-Status "Backend HTTP interface is still unavailable. Frontend may show startup gating until backend responds." "Warning"
        }
    }

    # Active listen check — someone else is really holding the port
    if (Test-PortActiveListen -Port $frontendPort) {
        $proc = Get-ProcessUsingPortListening -Port $frontendPort
        Write-Status "Port $frontendPort is already in use by process: $($proc.ProcessName) (PID: $($proc.Id))" "Error"
        return $false
    }

    # TIME_WAIT check — wait for it to clear before starting the new dev server
    if (Test-PortHasAnyConnection -Port $frontendPort) {
        Write-Status "Port $frontendPort has stale connections (TIME_WAIT). Waiting up to 60s..." "Warning"
        if (-not (Wait-PortCompletelyFree -Port $frontendPort -MaxWaitSeconds 60)) {
            Write-Status "Port $frontendPort still busy after 60s. Aborting." "Error"
            return $false
        }
        Write-Status "Port $frontendPort is now free." "Success"
    }

    $frontendDir = Join-Path $Config.ProjectRoot "ExecutionView\frontend"
    $logDir = Join-Path $Config.ProjectRoot $Config.LogDir
    if (-not (Test-Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }

    Clear-OldServiceLogs -LogDir $logDir -Prefix "frontend"

    $logFile = Join-Path $logDir "frontend-$(Get-Date -Format 'yyyyMMdd-HHmmss').log"
    $script = if ($Environment -eq "dev") { $Config.Frontend.DevScript } else { $Config.Frontend.ProdScript }

    Write-Status "Starting frontend (log: $logFile)..." "Info"

    # Use cmd.exe to redirect stdout/stderr to the log file.
    # This avoids .NET's redirected pipe buffers which nobody reads —
    # when the 4 KB pipe fills, Vite blocks on Console.Write and can no
    # longer serve HTTP requests, causing the black-screen bug.
    $startInfo = New-Object System.Diagnostics.ProcessStartInfo
    $startInfo.FileName = "cmd"
    $startInfo.Arguments = "/c cd /d `"$frontendDir`" && $script >> `"$logFile`" 2>&1"
    $startInfo.WorkingDirectory = $frontendDir
    $startInfo.UseShellExecute = $false
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

    Show-BackendStartupSummary -BackendStatus $status.Backend -IncludeHealthLine

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
    $logRoot = Join-Path $Config.ProjectRoot "logs"

    if (-not (Test-Path $logRoot)) {
        Write-Status "Log directory not found: $logRoot" "Error"
        return
    }

    $logFiles = Get-ChildItem -Path $logRoot -Recurse -Filter "*.log" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 15

    if ($logFiles.Count -eq 0) {
        Write-Status "No log files found" "Warning"
        return
    }

    Write-Separator
    Write-Status "Recent Log Files" "Info"
    Write-Separator

    $index = 1
    foreach ($file in $logFiles) {
        $relDir = $file.DirectoryName.Substring($logRoot.Length).TrimStart('\')
        $size = if ($file.Length -gt 1MB) {
            "{0:N2} MB" -f ($file.Length / 1MB)
        }
        else {
            "{0:N2} KB" -f ($file.Length / 1KB)
        }
        $label = if ($relDir) { "$relDir/$($file.Name)" } else { $file.Name }
        Write-Host "$index. $label" -ForegroundColor Cyan -NoNewline
        Write-Host " ($size, $($file.LastWriteTime))" -ForegroundColor Gray
        $index++
    }

    Write-Separator
    Write-Host "Log root: $logRoot" -ForegroundColor Gray
    Write-Host "Use 'Get-Content <logfile> -Tail 50' to view recent entries" -ForegroundColor Yellow
}

# Main Script Logic
Write-Separator
Write-Status "EMSXView Trading Tool - Service Manager" "Info"
Write-Status "Action: $Action | Environment: $Environment" "Info"
Write-Separator

switch ($Action) {
    "start" {
        $backendStarted = Start-BackendService
        if ($backendStarted) {
            $frontendStarted = Start-FrontendService -WaitForBackend $true
            $serviceStatus = Get-ServiceStatus
            Write-Separator
            Write-Status "Backend Startup Summary" "Info"
            Show-BackendStartupSummary -BackendStatus $serviceStatus.Backend -IncludeHealthLine
            if (-not $frontendStarted) {
                Write-Status "Frontend failed to start cleanly. Backend summary shown above." "Warning"
                exit 1
            }
        }
        else {
            Write-Status "Backend failed to start. Frontend will not be started." "Error"
            exit 1
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
        if (-not $backendStarted) {
            Write-Status "Backend failed to start. Aborting." "Error"
            exit 1
        }
        $frontendStarted = Start-FrontendService -WaitForBackend $true
        $serviceStatus = Get-ServiceStatus
        Write-Separator
        Write-Status "Backend Startup Summary" "Info"
        Show-BackendStartupSummary -BackendStatus $serviceStatus.Backend -IncludeHealthLine
        if (-not $frontendStarted) {
            Write-Status "Frontend failed to start cleanly. Backend summary shown above." "Warning"
            exit 1
        }
    }
    "status" {
        Show-ServiceStatus
    }
    "logs" {
        Show-Logs
    }
    "wait-frontend" {
        $frontendPort = if ($Environment -eq "dev") { $Config.Frontend.DevPort } else { $Config.Frontend.ProdPort }
        $url = "http://localhost:$frontendPort"
        $maxSec = 90

        Write-Status "Waiting for frontend to be ready at $url (up to ${maxSec}s)..." "Info"

        for ($i = 0; $i -lt $maxSec; $i++) {
            try {
                $req = [System.Net.HttpWebRequest]::Create($url)
                $req.Timeout = 3000
                $resp = $req.GetResponse()
                $code = [int]$resp.StatusCode
                $resp.Close()
                if ($code -eq 200) {
                    Write-Status "Frontend is ready (HTTP 200 after ${i}s)" "Success"
                    exit 0
                }
            }
            catch {
                # Not ready yet
            }

            if ($i % 5 -eq 0 -and $i -gt 0) {
                Write-Status "  ... still waiting ($i s elapsed)" "Warning"
            }
            Start-Sleep -Seconds 1
        }

        Write-Status "Frontend did not become ready within ${maxSec}s" "Error"
        exit 1
    }
    "kill" {
        Write-Status "Force killing all related processes..." "Warning"
        Stop-FrontendService
        Stop-BackendService
        Get-Process | Where-Object { $_.ProcessName -in @("python", "python3", "node") } | ForEach-Object {
            try {
                $procInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($_.Id)"
                if ($procInfo.CommandLine -like "*EMSXView*" -or $procInfo.CommandLine -like "*emsxview*") {
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
