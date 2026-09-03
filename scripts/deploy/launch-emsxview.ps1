#requires -Version 5.1
<#
.SYNOPSIS
    EMSXView 一键启动器（主入口）

.DESCRIPTION
    通过向上查找 `.emsxview-root` marker 定位项目根，从根本上消除
    "向上 N 层"硬编码——任何 .ps1 被移动到任意深度子目录都能正确定位。

    由 scripts/deploy/launch-emsxview.vbs（VBS 细封装）调用。
    桌面快捷方式 -> wscript.exe -> launch-emsxview.vbs -> 本脚本

.NOTES
    设计目标：
      1. 项目根查找唯一信息源 = `.emsxview-root` marker
      2. 启动前显式断言项目根有效，错路径立刻报错而非等 120s 超时
      3. 所有业务逻辑（端口轮询、错误页生成）集中在 PowerShell，消除 VBS/PS1 语义错位
      4. 后端、前端并行启动；前端优先打开浏览器，不被后端 60s+ 启动阻塞
#>

# ---- 配置 ----
$Script:Config = @{
    FrontendPort       = 5173
    BackendPort        = 3000
    FrontendTimeoutSec = 120   # 前端最多等 120 秒（Vite 冷启动较快）
    BackendTimeoutSec  = 180   # 后端最多等 180 秒（Bloomberg BPIPE 初始化需 30-120s）
    PollIntervalMs    = 1000
    HttpProbeTimeoutMs = 800
}

# ---- 工具函数 ----

function Find-EmsxviewRoot {
    <#
    .SYNOPSIS
        向上查找 `.emsxview-root` marker 定位项目根。
        兜底回退到 $PSScriptRoot\..\..（保持与现存脚本兼容）。
    #>
    $current = (Resolve-Path -LiteralPath $PSScriptRoot).Path
    while ($true) {
        $marker = Join-Path $current '.emsxview-root'
        if (Test-Path -LiteralPath $marker -PathType Leaf) {
            return $current
        }
        $parent = Split-Path $current -Parent
        if ([string]::IsNullOrEmpty($parent) -or $parent -eq $current) { break }
        $current = $parent
    }
    # 兜底：保持与传统脚本一致的"向上两层"
    return (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..')).Path
}

function Assert-ProjectRootValid {
    <#
    .SYNOPSIS
        对解析出的项目根做硬性断言。
        错路径立刻 throw，避免传统静默 120s 超时。
    #>
    param([string]$Root)
    $markers = @('frontend\package.json', 'backend\api\main.py', '.emsxview-root')
    foreach ($rel in $markers) {
        if (-not (Test-Path -LiteralPath (Join-Path $Root $rel))) {
            throw "项目根无效: '$Root'（缺少 $rel）。请确认 .emsxview-root 与项目结构完整。"
        }
    }
}

function Start-HiddenScript {
    <#
    .SYNOPSIS
        隐藏窗口、不阻塞地启动一个 .ps1 子脚本。
    #>
    param([string]$ScriptPath)
    if (-not (Test-Path -LiteralPath $ScriptPath)) {
        throw "启动脚本不存在: $ScriptPath"
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = 'powershell.exe'
    $psi.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    [void][System.Diagnostics.Process]::Start($psi)
}

function Test-PortHttpReady {
    <#
    .SYNOPSIS
        HTTP 探测端口是否就绪。任何 HTTP 状态码 > 0 视为就绪
        （Vite/uvicorn 绑定后会立即响应；404/500 也意味着服务已起）。
        依次尝试 127.0.0.1 和 localhost，兼容后端仅绑定 IPv4 或前端仅绑定 IPv6 的情况。
    #>
    param([int]$Port)
    foreach ($probeHost in @('127.0.0.1', 'localhost')) {
        $url = "http://${probeHost}:$Port/"
        try {
            $req = [System.Net.HttpWebRequest]::Create($url)
            $req.Timeout = $Script:Config.HttpProbeTimeoutMs
            $req.ReadWriteTimeout = $Script:Config.HttpProbeTimeoutMs
            $req.AllowAutoRedirect = $false
            $req.Proxy = $null
            $resp = $req.GetResponse()
            $code = [int]$resp.StatusCode
            $resp.Close()
            if ($code -gt 0) { return $true }
        }
        catch [System.Net.WebException] {
            # 404/500 仍会抛 WebException 但带 Response，视为就绪
            if ($_.Exception.Response) {
                try { $_.Exception.Response.Close() } catch {}
                return $true
            }
        }
        catch {}
    }
    return $false
}

function Wait-PortReady {
    <#
    .SYNOPSIS
        轮询端口就绪。返回 $true / $false。
    #>
    param([int]$Port, [int]$TimeoutSec, [string]$Label)
    $elapsed = 0
    while ($elapsed -lt $TimeoutSec) {
        if (Test-PortHttpReady -Port $Port) { return $true }
        Start-Sleep -Milliseconds $Script:Config.PollIntervalMs
        $elapsed += [int]($Script:Config.PollIntervalMs / 1000)
    }
    return $false
}

function Get-LatestStartupLog {
    <#
    .SYNOPSIS
        扫描 logs/ 找最新非启动-error 自身的日志文件。
        过滤掉与本启动无关的运维日志（observation/retire/migrate/sync 等）。
    #>
    param([string]$LogRoot)
    if (-not (Test-Path -LiteralPath $LogRoot)) { return $null }

    $excludePrefixes = @('observation_', 'retire_', 'migrate_', 'sync_', 'shrink_', 'cleanup_b4_', 'verify_')
    $candidates = Get-ChildItem -Path $LogRoot -Recurse -Filter '*.log' -File -ErrorAction SilentlyContinue |
        Where-Object {
            $name = $_.Name.ToLowerInvariant()
            $excluded = $false
            foreach ($p in $excludePrefixes) {
                if ($name.StartsWith($p)) { $excluded = $true; break }
            }
            -not $excluded
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1

    return $candidates
}

function Get-PortOccupancyInfo {
    <#
    .SYNOPSIS
        检查端口占用情况。返回字符串（用于错误页面展示）。
    #>
    param([int]$Port)
    try {
        $lines = netstat -ano | Where-Object { $_ -match (":$Port\s.*LISTENING") }
        if ($lines) {
            return ($lines -join "`r`n")
        }
    }
    catch {}
    return $null
}

function Test-PortListening {
    <#
    .SYNOPSIS
        检查指定端口是否处于 LISTEN 状态（不依赖 HTTP 响应）。
    #>
    param([int]$Port)
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        return $null -ne $connection
    }
    catch {
        return $false
    }
}

function Get-ProcessUsingPort {
    <#
    .SYNOPSIS
        返回正在监听指定端口的进程对象（如有）。
    #>
    param([int]$Port)
    try {
        $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        if ($connection) {
            return Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
        }
    }
    catch {}
    return $null
}

function Test-BackendAlreadyHealthy {
    <#
    .SYNOPSIS
        探测 127.0.0.1:<Port>/api/health 是否返回 HTTP 200。
        只要后端已绑定端口并能响应，即视为“已有可用后端”。
    #>
    param([int]$Port)
    $url = "http://127.0.0.1:$Port/api/health"
    try {
        $req = [System.Net.HttpWebRequest]::Create($url)
        $req.Timeout = $Script:Config.HttpProbeTimeoutMs
        $req.ReadWriteTimeout = $Script:Config.HttpProbeTimeoutMs
        $req.AllowAutoRedirect = $false
        $req.Proxy = $null
        $resp = $req.GetResponse()
        $code = [int]$resp.StatusCode
        $resp.Close()
        return $code -eq 200
    }
    catch [System.Net.WebException] {
        if ($_.Exception.Response) { try { $_.Exception.Response.Close() } catch {} }
        return $false
    }
    catch {
        return $false
    }
}

function Write-StartupErrorPage {
    <#
    .SYNOPSIS
        生成启动失败诊断 HTML 并在浏览器中打开。
        取代原 launch-emsxview.vbs 中 ShowErrorPage 子程序。
    #>
    param(
        [string]$ProjectRoot,
        [string]$ServiceName,
        [int]$Port,
        [int]$TimeoutSec,
        [string[]]$PossibleCauses,
        [bool]$FrontendOpened
    )

    $logRoot    = Join-Path $ProjectRoot 'logs'
    $errorPath  = Join-Path $logRoot 'startup-error.html'
    if (-not (Test-Path -LiteralPath $logRoot)) {
        New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
    }

    # Get the latest log (prefer full vite-startup.log on frontend failure)
    $logHint = ''
    if ($ServiceName -eq 'Frontend') {
        $viteLog = Join-Path $logRoot 'vite-startup.log'
        if (Test-Path -LiteralPath $viteLog) {
            $lines = Get-Content -LiteralPath $viteLog -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($lines) {
                $escaped = ($lines | ForEach-Object { [System.Net.WebUtility]::HtmlEncode($_) }) -join "`n"
                $logHint = "<p>Frontend startup log: <code>vite-startup.log</code></p><details open><summary>View all $($lines.Count) log lines</summary><pre>$escaped</pre></details>"
            }
        }
    }
    if ([string]::IsNullOrEmpty($logHint)) {
        $latest = Get-LatestStartupLog -LogRoot $logRoot
        if ($latest) {
            $lines = Get-Content -LiteralPath $latest.FullName -Encoding UTF8 -ErrorAction SilentlyContinue
            if ($lines) {
                $tailCount = [Math]::Min(30, $lines.Count)
                $tailStart = $lines.Count - $tailCount
                $tail = $lines | Select-Object -Skip $tailStart
                $escaped = ($tail | ForEach-Object { [System.Net.WebUtility]::HtmlEncode($_) }) -join "`n"
                $logHint = "<p>Latest log file: <code>$($latest.Name)</code> ($($latest.LastWriteTime))</p><details><summary>View last $tailCount log lines</summary><pre>$escaped</pre></details>"
            }
        }
    }

    $portInfo = Get-PortOccupancyInfo -Port $Port
    $portBlock = if ($portInfo) {
        "<div class='warning'>⚠ Port $Port is currently occupied:<pre>$([System.Net.WebUtility]::HtmlEncode($portInfo))</pre></div>"
    } else { '' }

    $frontendHint = if ($FrontendOpened) {
        "<div class='warning'>ℹ Frontend already opened: <code>http://localhost:$($Script:Config.FrontendPort)</code>. You may wait for the backend to become ready on the page, and refer to this diagnostic page for further troubleshooting.</div>"
    } else { '' }

    $causesHtml = ($PossibleCauses | ForEach-Object { "    <li>$_</li>" }) -join "`n"

    $html = @"
<!DOCTYPE html>
<html lang='en'>
<head>
<meta charset='UTF-8'>
<title>EMSXView - $ServiceName startup failed</title>
<style>
body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; padding: 32px; }
.card { max-width: 720px; margin: 0 auto; background: #1e293b; padding: 32px; border-radius: 16px; box-shadow: 0 25px 50px rgba(0,0,0,.4); }
h1 { color: #f87171; font-size: 22px; margin: 16px 0 8px; }
.subtitle { color: #94a3b8; margin-bottom: 24px; font-size: 14px; }
h2 { color: #fbbf24; font-size: 15px; margin: 20px 0 12px; }
ul, pre { margin: 0 0 16px; }
li { color: #cbd5e1; margin-bottom: 8px; font-size: 14px; line-height: 1.6; }
code { background: #334155; padding: 2px 6px; border-radius: 4px; font-size: 13px; color: #7dd3fc; }
pre { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 16px; overflow: auto; max-height: 300px; font-size: 12px; color: #94a3b8; white-space: pre-wrap; }
details { margin: 12px 0; }
summary { cursor: pointer; color: #7dd3fc; font-size: 14px; }
.warning { background: #422006; border: 1px solid #92400e; border-radius: 8px; padding: 12px 16px; margin: 12px 0; }
.actions { margin-top: 20px; }
.btn { display: inline-block; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-size: 14px; font-weight: 600; margin-right: 12px; }
.btn-primary { background: #3b82f6; color: white; }
.btn-secondary { background: #334155; color: #e2e8f0; }
.footer { color: #475569; font-size: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid #334155; }
</style>
</head>
<body>
<div class='card'>
  <h1>EMSXView $ServiceName startup failed</h1>
  <p class='subtitle'>Service failed to become ready within $TimeoutSec seconds (localhost:$Port)</p>
  $frontendHint
  $portBlock
  <h2>Possible Causes</h2>
  <ul>
$causesHtml
  </ul>
  <h2>Log Information</h2>
  $logHint
  <h2>Quick Fix</h2>
  <ul>
    <li>Open PowerShell, run <code>cd $ProjectRoot\scripts</code> then <code>.\stop-all.bat</code> to stop lingering processes</li>
    <li>Run <code>scripts\restart-all.bat</code> in visible-window mode to see the actual error</li>
  </ul>
  <div class='actions'>
    <a class='btn btn-primary' href='file:///$($errorPath -replace '\\','/')' onclick='location.reload()'>Retry</a>
    <a class='btn btn-secondary' href='http://localhost:$Port'>Reconnect</a>
  </div>
  <div class='footer'>EMSXView Trading Platform · $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')</div>
</div>
</body>
</html>
"@

    Set-Content -LiteralPath $errorPath -Value $html -Encoding UTF8
    Start-Process "file:///$($errorPath -replace '\\','/')"
}

# ---- 主流程 ----
# 标准 PowerShell 守卫：被 dot-source（用于函数测试）时跳过主流程；
# 直接 `powershell -File` 执行时正常运行。
if ($MyInvocation.InvocationName -eq '.') { return }

$ErrorActionPreference = 'Stop'

Write-Host '[launch] Locating project root...' -ForegroundColor Cyan
$ProjectRoot = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $ProjectRoot
Write-Host "[launch] Project root: $ProjectRoot" -ForegroundColor Green

# 后端预检：如果 3000 已被健康后端占用，直接复用，避免重复启动导致端口冲突
Write-Host '[launch] Checking backend port occupancy...' -ForegroundColor Cyan
$backendAlreadyRunning = $false
if (Test-PortListening -Port $Script:Config.BackendPort) {
    if (Test-BackendAlreadyHealthy -Port $Script:Config.BackendPort) {
        Write-Host "[launch] Detected running backend on port $($Script:Config.BackendPort) responding to health check; reusing it" -ForegroundColor Green
        $backendAlreadyRunning = $true
    }
    else {
        Write-Host "[launch] Port $($Script:Config.BackendPort) is occupied but health check failed; terminating stale process..." -ForegroundColor Yellow
        $staleProc = Get-ProcessUsingPort -Port $Script:Config.BackendPort
        if ($staleProc) {
            try {
                Stop-Process -Id $staleProc.Id -Force -ErrorAction Stop
                Write-Host "[launch] Terminated stale process $($staleProc.ProcessName) (PID $($staleProc.Id))" -ForegroundColor Green
                Start-Sleep -Seconds 2
            }
            catch {
                Write-Host "[launch] Failed to terminate stale process: $($_.Exception.Message)" -ForegroundColor Red
            }
        }
    }
}

# 并行启动后端、前端（隐藏窗口）
Write-Host '[launch] Starting backend / frontend in parallel (hidden window)...' -ForegroundColor Cyan
if (-not $backendAlreadyRunning) {
    Start-HiddenScript -ScriptPath (Join-Path $ProjectRoot 'scripts\deploy\start-backend.ps1')
}
Start-HiddenScript -ScriptPath (Join-Path $ProjectRoot 'scripts\deploy\start-frontend.ps1')

# 前端优先：等待 5173 就绪并打开浏览器
$frontendReady = Wait-PortReady `
    -Port  $Script:Config.FrontendPort `
    -TimeoutSec $Script:Config.FrontendTimeoutSec `
    -Label 'Frontend'

if (-not $frontendReady) {
    $causes = @(
        'node_modules not installed (run npm install under frontend/)',
        'Port 5173 occupied by another process (previous run not closed properly)',
        'Node.js / npm not installed or not in PATH',
        'npm SSL certificate issue (run npm config set strict-ssl false)'
    )
    Write-StartupErrorPage `
        -ProjectRoot $ProjectRoot `
        -ServiceName 'Frontend' `
        -Port $Script:Config.FrontendPort `
        -TimeoutSec $Script:Config.FrontendTimeoutSec `
        -PossibleCauses $causes `
        -FrontendOpened $false
    Write-Host '[launch] Frontend failed to start; diagnostic page generated' -ForegroundColor Red
    exit 1
}

Write-Host '[launch] Frontend ready; opening browser...' -ForegroundColor Green
Start-Process "http://localhost:$($Script:Config.FrontendPort)"

# 若已复用健康后端，无需再等待新实例启动
if ($backendAlreadyRunning) {
    Write-Host '[launch] Reusing running backend; startup complete' -ForegroundColor Green
    exit 0
}

# 后端不阻塞前端浏览器：继续等 3000
$backendReady = Wait-PortReady `
    -Port  $Script:Config.BackendPort `
    -TimeoutSec $Script:Config.BackendTimeoutSec `
    -Label 'Backend'

if (-not $backendReady) {
    $causes = @(
        'Python environment not found (check python.exe in PATH)',
        'Port 3000 occupied by another process (previous run not closed properly)',
        'Missing dependencies (run pip install under backend/)',
        'Bloomberg BPIPE connection failed (check if Terminal is online)'
    )
    Write-StartupErrorPage `
        -ProjectRoot $ProjectRoot `
        -ServiceName 'Backend' `
        -Port $Script:Config.BackendPort `
        -TimeoutSec $Script:Config.BackendTimeoutSec `
        -PossibleCauses $causes `
        -FrontendOpened $true
    Write-Host '[launch] Backend failed to start; diagnostic page generated' -ForegroundColor Red
    exit 1
}

Write-Host '[launch] Backend ready. Startup complete.' -ForegroundColor Green
exit 0