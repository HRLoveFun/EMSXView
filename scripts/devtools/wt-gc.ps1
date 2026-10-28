# wt-gc.ps1 — worktree 残留目录的主动识别与自动清理（035 长效化）
# 用法: ./scripts/devtools/wt-gc.ps1 [[-Task] <任务名...>] [-Apply] [-Force] [-KillHolders] [-MaxRetries 3] [-ScanRoot <dir>] [-Quiet] [-Json]
#
# 定位：wt-clean.ps1 解决「怎么安全地清」，本脚本解决「谁来发现、失败怎么办、如何不再复发」：
#   1. 主动识别：扫描兄弟目录 EMSXView-wt-*，凡不在 git worktree list 的即为孤儿残留；
#   2. 分级清理：空目录 / 仅缓存目录（node_modules 等）默认自动清；含其他文件须 -Force 且指名任务；
#   3. 句柄处置：删除失败时按「CommandLine 含目标路径」或「进程工作目录落在目标内」定位占用进程，
#      仅终止白名单解释器（bash/node/python/powershell），绝不触碰 explorer / Code 等 GUI 宿主，
#      也不触碰当前进程链；CWD 命中时额外排除交互终端（powershell/pwsh），避免误杀用户的 shell 窗口；
#   4. 失败登记：仍删不掉的写 logs/wt-gc-report.json，下次运行继续尝试（退出码 1 供计划任务告警）。
#
# 安全边界（与 wt-clean.ps1 一致，破坏性动作永不默认生效）：
#   - 默认 dry-run；删除须显式 -Apply；含非缓存内容的目录须 -Force 且显式指名 -Task；
#   - 主工作树、git 仍注册的 worktree、会话独占锁持有者一律不处理；
#   - 终止进程须同时满足：-KillHolders + 进程名白名单 + CommandLine 含目标绝对路径。
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string[]]$Task = @(),
    [switch]$Apply,
    [switch]$Force,
    [switch]$KillHolders,
    [int]$MaxRetries = 3,
    [int]$RetryDelaySeconds = 2,
    [string]$ScanRoot = "",
    [int]$TmpMinAgeMinutes = 30,
    [switch]$Quiet,
    [switch]$Json
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root
if (-not $ScanRoot) { $ScanRoot = Split-Path $root -Parent }
if ($MaxRetries -lt 1) { throw "-MaxRetries 必须 >= 1" }

$script:AllowedHolderNames = @("bash.exe", "sh.exe", "node.exe", "python.exe", "pythonw.exe", "powershell.exe", "pwsh.exe")
# CWD 命中时允许终止的进程名：交互终端（powershell/pwsh）常把工作目录留在 worktree 里，
# 只按 CWD 就终止会误杀用户窗口，故 CWD 维度仅对无交互语义的解释器生效。
$script:CwdKillNames = @("bash.exe", "sh.exe", "node.exe", "python.exe", "pythonw.exe")
$script:CacheLeafNames = @(
    "node_modules", "__pycache__", ".pytest_cache", ".vite", "dist", "logs",
    ".venv", "venv", ".mypy_cache", ".ruff_cache", "target", "bin", "obj"
)
$reportPath = Join-Path $root "logs/wt-gc-report.json"

function Write-GcLine {
    param([string]$Text)
    if (-not $Quiet) { Write-Output $Text }
}

function Get-NormalizedPath {
    param([string]$Path)
    return ([IO.Path]::GetFullPath($Path)).TrimEnd("\", "/")
}

# 孤儿目录：兄弟目录中带 EMSXView-wt- 前缀、存在、且不在 git worktree list
function Get-OrphanDirs {
    param([string]$Root, [string]$ScanRoot, [string[]]$Task)
    $registered = @(Get-WtEntries -Root $Root | Where-Object { -not $_.Bare } |
        ForEach-Object { Get-NormalizedPath -Path $_.Path })
    $mainPath = Get-NormalizedPath -Path $Root
    $dirs = @(Get-ChildItem -LiteralPath $ScanRoot -Directory -Filter "EMSXView-wt-*" -Force -ErrorAction SilentlyContinue)
    if ($Task.Count -gt 0) {
        $wanted = @($Task | ForEach-Object { if ($_ -like "EMSXView-wt-*") { $_ } else { "EMSXView-wt-$_" } })
        $dirs = @($dirs | Where-Object { $wanted -contains $_.Name })
    }
    $out = @()
    foreach ($dir in $dirs) {
        $full = Get-NormalizedPath -Path $dir.FullName
        if ($full -ieq $mainPath) { continue }
        if ($registered -contains $full) { continue }
        $out += $full
    }
    return $out
}

# 残留分级：empty / cache-only / temp-only（顶层仅 _tmp 且已静置）/ dirty
# temp-only 与 wt-clean 的「_tmp 在途保护」同口径：静置阈值内的 _tmp 仍视为在途，不自动清。
function Get-OrphanKind {
    param([string]$Path, [string]$Root, [int]$TmpMinAgeMinutes)
    $items = @(Get-ChildItem -LiteralPath $Path -Force -ErrorAction SilentlyContinue)
    if ($items.Count -eq 0) { return "empty" }
    $cacheOnly = $true
    foreach ($item in $items) {
        if (-not $item.PSIsContainer -or ($script:CacheLeafNames -notcontains $item.Name)) { $cacheOnly = $false; break }
    }
    if ($cacheOnly) { return "cache-only" }
    if ($items.Count -eq 1 -and $items[0].PSIsContainer -and $items[0].Name -eq "_tmp") {
        $cutoff = (Get-Date).AddMinutes(-$TmpMinAgeMinutes)
        if ($items[0].LastWriteTime -lt $cutoff) { return "temp-only" }
    }
    # 含 .git 的 worktree 残留：无未提交改动且分支已并入 origin/main → 可自动清（内容可再生成）
    if (Test-Path -LiteralPath (Join-Path $Path ".git")) {
        $branch = (& git -C $Path rev-parse --abbrev-ref HEAD 2>$null | Select-Object -First 1)
        if ($branch -and $branch -ne "HEAD" -and (Test-RefExists -Root $Root -Ref "origin/main")) {
            $dirtyCount = @(& git -C $Path status --porcelain 2>$null).Count
            if ($dirtyCount -eq 0 -and (Test-BranchMerged -Root $Root -Branch $branch)) {
                return "git-merged-clean"
            }
        }
    }
    return "dirty"
}

# 占用进程：进程名白名单 + （CommandLine 含目标绝对路径 或 工作目录落在目标内）
# 两个维度互补：前者覆盖 `python -m pytest <path>` 这类把路径写进命令行的场景，
# 后者覆盖 `Start-Process -WorkingDirectory` / 后台解释器等「命令行不含路径」的场景
# （此前这类进程无法定位，只能登记后等下次重试）。
function Get-HolderProcesses {
    param([string]$Path)
    $needle = ConvertTo-MatchablePath -Text $Path
    $self = $PID
    $parent = (Get-CimInstance Win32_Process -Filter "ProcessId = $self" -ErrorAction SilentlyContinue).ParentProcessId
    $out = @()
    foreach ($proc in @(Get-CimInstance Win32_Process -ErrorAction SilentlyContinue)) {
        if ($proc.ProcessId -eq $self -or $proc.ProcessId -eq $parent) { continue }
        $name = $proc.Name.ToLowerInvariant()
        if ($script:AllowedHolderNames -notcontains $name) { continue }

        $reason = ""
        if ($proc.CommandLine -and (ConvertTo-MatchablePath -Text $proc.CommandLine).Contains($needle)) {
            $reason = "cmdline"
        }
        $cwd = Get-ProcessWorkingDirectory -ProcessId $proc.ProcessId
        if (-not $reason -and (Test-PathWithin -Candidate $cwd -Parent $Path)) { $reason = "cwd" }
        if (-not $reason) { continue }

        $out += [pscustomobject]@{
            ProcessId = $proc.ProcessId
            Name      = $proc.Name
            Reason    = $reason
            Cwd       = $cwd
            Killable  = ($reason -eq "cmdline") -or ($script:CwdKillNames -contains $name)
        }
    }
    return $out
}

function Remove-OrphanDir {
    param([string]$Path, [int]$Retries, [bool]$Kill, [int]$DelaySeconds)
    $attempt = 0
    $killed = @()
    $lastError = ""
    while ($attempt -lt $Retries) {
        $attempt++
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop
            return [pscustomobject]@{ Removed = $true; Attempts = $attempt; Killed = $killed; Error = "" }
        }
        catch {
            $lastError = $_.Exception.Message
            if (-not $Kill) { break }
            $holders = @(Get-HolderProcesses -Path $Path)
            $killable = @($holders | Where-Object { $_.Killable })
            if ($killable.Count -eq 0) {
                # 两种情况都登记后由下次运行重试（计划任务每日自动跑）：
                #   a) 已识别但不在可终止名单（如工作目录在残留里的交互终端）；
                #   b) 完全无法识别（GUI/IDE、提权进程，或持有的是文件句柄而非工作目录）。
                $detail = if ($holders.Count -gt 0) {
                    "holder 已识别但不可自动终止：" +
                    (($holders | ForEach-Object { "{0}#{1}({2})" -f $_.Name, $_.ProcessId, $_.Reason }) -join ",")
                }
                else {
                    "holder 未识别（可能为 GUI/IDE、提权进程，或持有的是文件句柄而非工作目录）"
                }
                $lastError = $lastError + " | " + $detail + "，下次运行重试"
                Start-Sleep -Seconds $DelaySeconds
                continue
            }
            foreach ($holder in $killable) {
                try {
                    Stop-Process -Id $holder.ProcessId -Force -ErrorAction Stop
                    $killed += ("{0}#{1}" -f $holder.Name, $holder.ProcessId)
                }
                catch { }
            }
            Start-Sleep -Seconds $DelaySeconds
        }
    }
    return [pscustomobject]@{ Removed = $false; Attempts = $attempt; Killed = $killed; Error = $lastError }
}

# ---------- 采集 ----------
$orphans = @(Get-OrphanDirs -Root $root -ScanRoot $ScanRoot -Task $Task)
$forceArmed = ($Force -and $Task.Count -gt 0)
$results = @()

Write-GcLine "===GC PLAN==="
Write-GcLine ("[mode] {0}" -f $(if ($Apply) { "apply（执行删除）" } else { "dry-run（仅预演，加 -Apply 执行）" }))
Write-GcLine ("[kill-holders] {0}" -f $(if ($KillHolders) { "on（白名单解释器）" } else { "off" }))
if ($Force -and -not $forceArmed) { Write-GcLine "[force] on 但未指名任务：含其他内容的目录不处理" }
if ($orphans.Count -eq 0) { Write-GcLine "[orphan] 无残留目录" }

# ---------- 执行 ----------
$removed = 0
$skipped = 0
$failed = 0
foreach ($path in $orphans) {
    $kind = Get-OrphanKind -Path $path -Root $root -TmpMinAgeMinutes $TmpMinAgeMinutes
    $cleanable = ($kind -eq "empty") -or ($kind -eq "cache-only") -or ($kind -eq "temp-only") -or ($kind -eq "git-merged-clean") -or $forceArmed
    if (-not $cleanable) {
        Write-GcLine ("[skip] {0} | {1} | 含非缓存内容，需 -Force 且显式指名任务" -f $path, $kind)
        $skipped++
        $results += [pscustomobject]@{ path = $path; kind = $kind; action = "skipped"; removed = $false; attempts = 0; killed = @(); error = "" }
        continue
    }
    if (-not $Apply) {
        Write-GcLine ("[plan] {0} | {1} | 可清理" -f $path, $kind)
        $results += [pscustomobject]@{ path = $path; kind = $kind; action = "planned"; removed = $false; attempts = 0; killed = @(); error = "" }
        continue
    }
    $outcome = Remove-OrphanDir -Path $path -Retries $MaxRetries -Kill $KillHolders.IsPresent -DelaySeconds $RetryDelaySeconds
    if ($outcome.Removed) {
        Write-GcLine ("[ok] {0} | {1} | attempts={2}{3}" -f $path, $kind, $outcome.Attempts,
            $(if ($outcome.Killed.Count -gt 0) { " | killed=" + ($outcome.Killed -join ",") } else { "" }))
        $removed++
        $results += [pscustomobject]@{ path = $path; kind = $kind; action = "removed"; removed = $true; attempts = $outcome.Attempts; killed = $outcome.Killed; error = "" }
    }
    else {
        Write-GcLine ("[fail] {0} | {1} | attempts={2} | {3}" -f $path, $kind, $outcome.Attempts, $outcome.Error)
        $failed++
        $results += [pscustomobject]@{ path = $path; kind = $kind; action = "failed"; removed = $false; attempts = $outcome.Attempts; killed = $outcome.Killed; error = $outcome.Error }
    }
}

# ---------- 登记 ----------
if ($Apply -and $orphans.Count -gt 0) {
    try {
        Invoke-Git -C $root worktree prune
        Write-GcLine "[ok] 已执行 git worktree prune"
    }
    catch { Write-GcLine "[warn] git worktree prune 失败：$($_.Exception.Message)" }
    $logDir = Split-Path $reportPath -Parent
    if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
    $report = [pscustomobject]@{
        generated_at = (Get-Date).ToString("o")
        scan_root    = $ScanRoot
        removed      = $removed
        skipped      = $skipped
        failed       = $failed
        entries      = $results
    }
    ($report | ConvertTo-Json -Depth 5) | Set-Content -LiteralPath $reportPath -Encoding UTF8
}

if ($Json) { ($results | ConvertTo-Json -Depth 5) }
Write-GcLine "===GC RESULT==="
Write-GcLine ("removed={0} skipped={1} failed={2}" -f $removed, $skipped, $failed)
if ($failed -gt 0) { exit 1 }
