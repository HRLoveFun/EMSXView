# wt-clean.ps1 — 清理 worktree 残留与 _tmp 临时目录（默认仅预演，-Apply 才真正删除）
# 用法: ./scripts/devtools/wt-clean.ps1 [[-Task] <任务名...>] [-Apply] [-Force] [-SkipTmp] [-TmpMinAgeMinutes 30]
# 定位: 把「移除 worktree + prune + 清 _tmp + 打印状态」收敛为单条命令，供 Agent 免逐次审批执行；
#       破坏性边界全部由本脚本内的硬校验承担（对齐 docs/spec/git-workflow.md §9/§10 与 ADR-0700）。
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

# 判定单个候选：可清理 / 需 -Force / 原因
function New-WtCandidate {
    param([string]$Dir, [string]$Root, [object[]]$GitEntries)
    $known = $GitEntries | Where-Object { Test-SamePath -A $_.Path -B $Dir } | Select-Object -First 1
    if (-not $known) {
        return [pscustomobject]@{ Path = $Dir; Branch = ""; Kind = "orphan"; Removable = $false; Reason = "git 已不认（孤儿残留目录），需 -Force" }
    }
    $branch = $known.Branch
    $dirty = @(& git -C $Dir status --porcelain).Count
    if ($dirty -gt 0) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Reason = "有未提交改动 $dirty 项，需 -Force" }
    }
    if (-not $branch) {
        return [pscustomobject]@{ Path = $Dir; Branch = ""; Kind = "worktree"; Removable = $true; Reason = "detached HEAD 且无改动" }
    }
    if (-not (Test-RefExists -Root $Root -Ref "origin/main")) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Reason = "origin/main 不存在，无法判定合并，需 -Force" }
    }
    if (Test-BranchMerged -Root $Root -Branch $branch) {
        return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $true; Reason = "分支 $branch 已合并进 origin/main" }
    }
    return [pscustomobject]@{ Path = $Dir; Branch = $branch; Kind = "worktree"; Removable = $false; Reason = "分支 $branch 尚未合并，需 -Force" }
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
$gitEntries = @(Get-WtEntries -Root $root | Where-Object { -not $_.Bare })
$candidates = @(Get-TargetDirs -Root $root -Task $Task |
    Where-Object { -not (Test-SamePath -A $_ -B $root) } |
    ForEach-Object { New-WtCandidate -Dir $_ -Root $root -GitEntries $gitEntries })
$tmpCandidates = if ($SkipTmp) { @() } else { Get-TmpCandidates -Root $root -MinAgeMinutes $TmpMinAgeMinutes }

# ---------- 计划 ----------
Write-Output "===PLAN==="
Write-Output "[mode] $(if ($Apply) { 'apply（执行删除）' } else { 'dry-run（仅预演，加 -Apply 执行）' })"
Write-Output "[force] $(if ($Force) { 'on（含未合并/脏 worktree/孤儿目录/在途 _tmp）' } else { 'off' })"
if ($candidates.Count -eq 0) { Write-Output "[worktree] 无待清理目录" }
foreach ($c in $candidates) {
    Write-Output "[worktree] $($c.Path) | $(if ($c.Removable) { '可清理' } else { '需 -Force' }) | $($c.Reason)"
}
if ($SkipTmp) { Write-Output "[tmp] 已跳过（-SkipTmp）" }
elseif ($tmpCandidates.Count -eq 0) { Write-Output "[tmp] 无待清理项" }
else {
    foreach ($t in $tmpCandidates) {
        Write-Output "[tmp] $($t.Name) | $(if ($t.InFlight) { '在途（默认跳过，-Force 可覆盖）' } else { '可清理' })"
    }
}

# ---------- 执行 ----------
$removed = 0
$failed = 0
if ($Apply) {
    foreach ($c in $candidates) {
        if (-not $c.Removable -and -not $Force) { Write-Output "[skip] $($c.Path)（需 -Force）"; continue }
        try { $msg = Remove-WtCandidate -Root $root -Candidate $c; Write-Output "[ok] $msg：$($c.Path)"; $removed++ }
        catch { Write-Output "[fail] $($c.Path)：$($_.Exception.Message)"; $failed++ }
    }
    foreach ($t in $tmpCandidates) {
        if ($t.InFlight -and -not $Force) { Write-Output "[skip] _tmp/$($t.Name)（在途）"; continue }
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
