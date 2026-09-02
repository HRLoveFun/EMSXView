# wt-finish.ps1 — 完成任务：校验分支已合并 → 移除 worktree → prune → 可选删除本地分支
# 用法: ./scripts/devtools/wt-finish.ps1 <task> [-DeleteBranch] [-Force]
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Task,
    [switch]$DeleteBranch,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

$dir = Join-Path (Split-Path $root -Parent) "EMSXView-wt-$Task"
if (-not (Test-Path $dir)) { throw "worktree 目录不存在: $dir（用 wt-list.ps1 查看现有 worktree）" }

$branch = (& git -C $dir branch --show-current)
if ($branch -and -not $Force) {
    $merged = Test-BranchMerged -Root $root -Branch $branch
    if (-not $merged) {
        Write-Host "[fail] 分支 $branch 尚未合并进 origin/main，拒绝移除" -ForegroundColor Red
        Write-Host "       若已通过 squash merge 完成合并，确认无误后加 -Force 重试" -ForegroundColor Red
        exit 1
    }
}

$removeArgs = @("worktree", "remove", $dir)
if ($Force) { $removeArgs += "--force" }
Invoke-Git -C $root @removeArgs
Invoke-Git -C $root worktree prune

if ($DeleteBranch -and $branch) {
    $branchArgs = @("branch")
    if ($Force) { $branchArgs += "-D" }
    else { $branchArgs += "-d" }
    $branchArgs += $branch
    Invoke-Git -C $root @branchArgs
    Write-Host "[ok] 已删除本地分支 $branch" -ForegroundColor Green
}

Write-Host "[ok] 已移除 worktree $dir" -ForegroundColor Green
