# wt-clean.ps1 — 清理 worktree 残留与 _tmp 临时目录（默认仅预演，-Apply 才真正删除）
# 用法: ./scripts/devtools/wt-clean.ps1 [[-Task] <任务名...>] [-Apply] [-Force] [-SkipTmp] [-TmpMinAgeMinutes 30]
# 定位: 把「移除 worktree + prune + 清 _tmp + 打印状态」收敛为单条命令，供 Agent 免逐次审批执行；
#       破坏性边界全部由本脚本内的硬校验承担（对齐 docs/spec/git-workflow.md §9/§10 与 ADR-0700）。
# 硬约束（2026-09-15 加固，起因：全量 -Force 扫描曾试图移除另一个会话含 674 项在途改动的 worktree）：
#   1. 锁保护：git `locked` 或存在会话独占锁（EMSXVIEW_SESSION_LOCK）的 worktree，**任何模式都不自动移除**；
#   2. 强制须指名：`-Force` 的强副作用（脏 worktree / 孤儿目录 / 在途 _tmp）只在**显式 -Task 指名**时生效，
#      未指名时全量扫描一律跳过并告警，避免连带破坏其他会话的在制品。
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string[]]$Task = @(),
    [switch]$Apply,
    [switch]$Force,
    [switch]$SkipTmp,
    [int]$TmpMinAgeMinutes = 30
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root
if ($TmpMinAgeMinutes -lt 0) { throw "-TmpMinAgeMinutes 不能为负" }

# 路径等价比较（归一化分隔符与大小写）
function Test-SamePath {
    param([string]$A, [string]$B)
    if (-not $A -or -not $B) { return $false }
    $pa = ([IO.Path]::GetFullPath($A)).TrimEnd("\", "/")
    $pb = ([IO.Path]::GetFullPath($B)).TrimEnd("\", "/")
    return ($pa -ieq $pb)
}

# 列举兄弟目录中符合 EMSXView-wt-* 的目标（-Task 为空表示全部）
# 硬边界：只扫描仓库根的兄弟目录且名称必须带 EMSXView-wt- 前缀，主工作树与任意路径天然被排除
function Get-TargetDirs {
    param([string]$Root, [string[]]$Task)
    $parent = Split-Path $Root -Parent
    $dirs = @(Get-ChildItem -LiteralPath $parent -Directory -Filter "EMSXView-wt-*" -Force -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    if ($Task.Count -eq 0) { return $dirs }
    $wanted = @($Task | ForEach-Object { if ($_ -like "EMSXView-wt-*") { $_ } else { "EMSXView-wt-$_" } })
    return @($dirs | Where-Object { $wanted -contains (Split-Path $_ -Leaf) })
}

# 解析 git worktree list --porcelain 中带 locked 标记的 worktree 路径
function Get-LockedWtPaths {
    param([string]$Root)
    $locked = @()
    $cur = $null
    foreach ($line in (& git -C $Root worktree list --porcelain)) {
        if ($line -like "worktree *") { $cur = $line.Substring(9) }
        elseif ($line -like "locked*" -and $cur) { $locked += $cur }
    }
    return $locked
}

# 该 worktree 是否存在会话独占锁文件（锁路径按工作树隔离，见 .githooks/common.sh 与规范 §10）
function Test-WtSessionLock {
    param([string]$Path)
    $gitDir = (& git -C $Path rev-parse --absolute-git-dir 2>$null | Select-Object -First 1)
    if (-not $gitDir) { return $false }
    return (Test-Path -LiteralPath (Join-Path $gitDir "EMSXVIEW_SESSION_LOCK"))
}

# 锁保护判定：返回原因字符串；空串表示无保护
function Test-WtGuarded {
    param([string]$Path, [string[]]$LockedPaths)
    if ($LockedPaths | Where-Object { Test-SamePath -A $_ -B $Path }) { return "git 已 lock（需人工 git worktree unlock 后处理）" }
    if (Test-WtSessionLock -Path $Path) { return "存在会话独占锁（可能有其他会话正在作业）" }
    return ""
}

# 判定单个候选：可清理 / 需 -Force / 有锁保护 / 原因
function New-WtCandidate {
    param([string]$Dir, [string]$Root, [object[]]$GitEntries, [string[]]$LockedPaths)
    $guard = Test-WtGuarded -Path $Dir -LockedPaths $LockedPaths
    if ($guard) {
        return [pscustomobject]@{ Path = $Dir; Branch = ""; Kind = "worktree"; Removable = $false; Locked = $true; Reason = $guard }
    }
    $known = $GitEntries | Where-Object { Test-SamePath -A $_.Path -B $Dir } | Select-Object -First 1
    if (-not $known) {
        return [pscustomobject]@{ Path = $Dir; Branch = ""; Kind = "orphan"; Removable = $false; Locked = $false; Reason = "git 已不认（孤儿残留目录），需 -Force" }
    }
    $branch = $known.Branch
    $dirty = @(& git -C $Dir status --porcelain).Count
    if ($dirty -gt 0) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Locked = $false; Reason = "有未提交改动 $dirty 项，需 -Force" }
    }
    if (-not $branch) {
        return [pscustomobject]@{ Path = $Dir; Branch = ""; Kind = "worktree"; Removable = $true; Locked = $false; Reason = "detached HEAD 且无改动" }
    }
    if (-not (Test-RefExists -Root $Root -Ref "origin/main")) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Locked = $false; Reason = "origin/main 不存在，无法判定合并，需 -Force" }
    }
    if (Test-BranchMerged -Root $Root -Branch $branch) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $true; Locked = $false; Reason = "分支 $branch 已合并进 origin/main" }
    }
    return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Locked = $false; Reason = "分支 $branch 尚未合并，需 -Force" }
}

# 移除单个候选：常规候选不带 --force（让 git 再兜底一次），需强制的候选才带 --force
function Remove-WtCandidate {
    param([string]$Root, [object]$Candidate)
    if ($Candidate.Kind -eq "orphan") {
        Remove-Item -LiteralPath $Candidate.Path -Recurse -Force
        return "已删除孤儿目录"
    }
    if ($Candidate.Removable) {
        Invoke-Git -C $Root worktree remove $Candidate.Path
        return "已移除 worktree（常规）"
    }
    Invoke-Git -C $Root worktree remove $Candidate.Path --force
    return "已移除 worktree（--force）"
}

# 采集 _tmp 直接子项；最近 MinAgeMinutes 分钟内变更的视为在途，默认跳过
function Get-TmpCandidates {
    param([string]$Root, [int]$MinAgeMinutes)
    $tmp = Join-Path $Root "_tmp"
    if (-not (Test-Path -LiteralPath $tmp)) { return @() }
    $cutoff = (Get-Date).AddMinutes(-$MinAgeMinutes)
    return @(Get-ChildItem -LiteralPath $tmp -Force | ForEach-Object {
            [pscustomobject]@{ Path = $_.FullName; Name = $_.Name; InFlight = ($_.LastWriteTime -gt $cutoff) }
        })
}

# ---------- 采集 ----------
$lockedPaths = @(Get-LockedWtPaths -Root $root)
$gitEntries = @(Get-WtEntries -Root $root | Where-Object { -not $_.Bare })
$candidates = @(Get-TargetDirs -Root $root -Task $Task |
    Where-Object { -not (Test-SamePath -A $_ -B $root) } |
    ForEach-Object { New-WtCandidate -Dir $_ -Root $root -GitEntries $gitEntries -LockedPaths $lockedPaths })
$tmpCandidates = if ($SkipTmp) { @() } else { Get-TmpCandidates -Root $root -MinAgeMinutes $TmpMinAgeMinutes }
$forceArmed = ($Force -and $Task.Count -gt 0)

# ---------- 计划 ----------
Write-Output "===PLAN==="
Write-Output "[mode] $(if ($Apply) { 'apply（执行删除）' } else { 'dry-run（仅预演，加 -Apply 执行）' })"
if ($forceArmed) { Write-Output "[force] on（已指名 $($Task -join ', ')）" }
elseif ($Force) { Write-Output "[force] on 但未指名任务：强删除不生效（防全量扫描连带破坏）" }
else { Write-Output "[force] off" }
if ($candidates.Count -eq 0) { Write-Output "[worktree] 无待清理目录" }
foreach ($c in $candidates) {
    $tag = if ($c.Locked) { '有锁保护（不移除）' }
    elseif ($c.Removable) { '可清理' }
    elseif ($forceArmed) { '可强制移除' }
    else { '需 -Force 且须指名' }
    Write-Output "[worktree] $($c.Path) | $tag | $($c.Reason)"
}
if ($SkipTmp) { Write-Output "[tmp] 已跳过（-SkipTmp）" }
elseif ($tmpCandidates.Count -eq 0) { Write-Output "[tmp] 无待清理项" }
else {
    foreach ($t in $tmpCandidates) {
        $tag = if (-not $t.InFlight) { '可清理' }
        elseif ($forceArmed) { '在途（-Force 将覆盖）' }
        else { '在途（跳过）' }
        Write-Output "[tmp] $($t.Name) | $tag"
    }
}

# ---------- 执行 ----------
$removed = 0
$failed = 0
if ($Apply) {
    foreach ($c in $candidates) {
        if ($c.Locked) { Write-Output "[skip] $($c.Path)（有锁保护，任何模式都不移除）"; continue }
        if (-not $c.Removable -and -not $forceArmed) { Write-Output "[skip] $($c.Path)（需 -Force 且须显式指名任务）"; continue }
        try { $msg = Remove-WtCandidate -Root $root -Candidate $c; Write-Output "[ok] $msg：$($c.Path)"; $removed++ }
        catch { Write-Output "[fail] $($c.Path)：$($_.Exception.Message)"; $failed++ }
    }
    foreach ($t in $tmpCandidates) {
        if ($t.InFlight -and -not $forceArmed) { Write-Output "[skip] _tmp/$($t.Name)（在途）"; continue }
        try { Remove-Item -LiteralPath $t.Path -Recurse -Force; Write-Output "[ok] 已删除 _tmp/$($t.Name)"; $removed++ }
        catch { Write-Output "[fail] _tmp/$($t.Name)：$($_.Exception.Message)"; $failed++ }
    }
    Invoke-Git -C $root worktree prune
    Write-Output "[ok] 已执行 git worktree prune"
}
else {
    & git -C $root worktree prune -n --verbose
    Write-Output "[dry-run] 未删除任何内容；确认无误后加 -Apply 执行"
}

# ---------- 状态汇总 ----------
Write-Output "===WORKTREE LIST==="
& git -C $root --no-pager worktree list
Write-Output "===STATUS==="
$statusLines = @(& git -C $root status --porcelain=v1)
if ($statusLines.Count -eq 0) { Write-Output "(clean)" } else { $statusLines }
Write-Output "===TMP DIR==="
$tmpDir = Join-Path $root "_tmp"
if (Test-Path -LiteralPath $tmpDir) {
    $left = @(Get-ChildItem -LiteralPath $tmpDir -Force | Select-Object -ExpandProperty Name)
    if ($left.Count -eq 0) { Write-Output "_tmp 已清空" } else { $left }
}
else { Write-Output "_tmp 不存在" }
Write-Output "===RESULT==="
Write-Output "removed=$removed failed=$failed"
if ($failed -gt 0) { exit 1 }
