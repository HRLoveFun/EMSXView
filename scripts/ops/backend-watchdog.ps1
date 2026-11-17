# EMSXView backend 看门狗：每 5 分钟由任务计划程序调用。
#
# 背景（2026-11-17）：Bloomberg 平台在 00:51 / 15:40 两次掉线后，backend 的
# blpapi 会话停止重连（`Platform failed 3 consecutive times`），进程仍在但行情
# 不再更新，shadow 直连侧数据停更。本脚本检测并重启。
#
# 判定：
#   - :3000 无监听            → 以 shadow 模式启动 backend
#   - /api/health 报 bloomberg 非 connected
#       ├─ 首次发现：记录时刻，等下一轮（避免启动瞬态误重启）
#       └─ 持续 ≥ StaleMinutes：restart（stop + start）
#   - 正常                    → 退出 0
#
param(
    [int]$Port = 3000,
    [string]$BaseUrl = 'http://127.0.0.1:3000',
    [string]$GatewayUrl = 'http://127.0.0.1:8101',
    [int]$StaleMinutes = 5
)

$ErrorActionPreference = 'Continue'
$Repo = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$ServiceManager = Join-Path $PSScriptRoot 'service-manager.ps1'
$LogDir = Join-Path $Repo 'logs\ops'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir 'backend-watchdog.log'
$State = Join-Path $LogDir 'backend-watchdog-state.json'

function Write-WatchLog([string]$Message) {
    $line = "{0} {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Message
    Add-Content -Path $Log -Value $line -Encoding utf8
}

function Test-PortListening {
    return [bool](Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

function Get-Health {
    try {
        return (Invoke-RestMethod -Uri "$BaseUrl/api/health" -TimeoutSec 5).data
    } catch {
        return $null
    }
}

function Get-ExtraTickers {
    $envFile = Join-Path $Repo '.env'
    if (-not (Test-Path $envFile)) { return '' }
    $line = Select-String -Path $envFile -Pattern '^EMSXVIEW_GATEWAY_SHADOW_EXTRA_TICKERS=(.*)$' |
        Select-Object -First 1
    if ($line) { return $line.Matches[0].Groups[1].Value.Trim() }
    return ''
}

function Set-ShadowEnv {
    $env:EMSXVIEW_GATEWAY_MODE = 'shadow'
    $env:EMSXVIEW_GATEWAY_URL = $GatewayUrl
    $extra = Get-ExtraTickers
    if ($extra) { $env:EMSXVIEW_GATEWAY_SHADOW_EXTRA_TICKERS = $extra }
}

$health = Get-Health
if (-not $health) {
    if (Test-PortListening) {
        Write-WatchLog "[warn] port $Port is listening but /api/health failed; not starting another instance"
        exit 1
    }
    Write-WatchLog "[start] backend $Port not running; starting in shadow mode"
    Set-ShadowEnv
    & $ServiceManager start
    $code = $LASTEXITCODE
    if ($code -eq 0) { Remove-Item $State -ErrorAction SilentlyContinue }
    Write-WatchLog "[start] service-manager exit=$code"
    exit $code
}

$status = $health.bloomberg.status
if ($status -eq 'connected') {
    Remove-Item $State -ErrorAction SilentlyContinue
    Write-WatchLog "[ok] backend healthy (bloomberg=$status)"
    exit 0
}

$now = Get-Date
$since = $null
if (Test-Path $State) {
    try {
        $saved = Get-Content -Path $State -Raw | ConvertFrom-Json
        if ($saved.status -eq $status -and $saved.since) {
            $since = [datetime]::Parse($saved.since)
        }
    } catch {
        $since = $null
    }
}

if ($null -eq $since) {
    @{ status = $status; since = $now.ToString('o') } | ConvertTo-Json | Set-Content -Path $State -Encoding utf8
    Write-WatchLog ("[warn] bloomberg=$status; recording first observation, will restart if still down in ${StaleMinutes}m")
    exit 0
}

$ageMinutes = ($now - $since).TotalMinutes
if ($ageMinutes -lt $StaleMinutes) {
    Write-WatchLog ("[warn] bloomberg=$status for {0:N1}m (<{1}m); waiting" -f $ageMinutes, $StaleMinutes)
    exit 0
}

Write-WatchLog ("[restart] bloomberg=$status for {0:N1}m; restarting backend in shadow mode" -f $ageMinutes)
Set-ShadowEnv
& $ServiceManager restart
$code = $LASTEXITCODE
if ($code -eq 0) { Remove-Item $State -ErrorAction SilentlyContinue }
Write-WatchLog "[restart] service-manager exit=$code"
exit $code
