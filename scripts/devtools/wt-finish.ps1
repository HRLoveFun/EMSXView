# wt-finish.ps1 — 完成任务：校验分支已合并 → 移除 worktree → prune → 可选删除本地分支
# 用法: ./scripts/devtools/wt-finish.ps1 <task> [-DeleteBranch] [-Force]
# 注意: 本仓库约定 squash merge —— 分支内容已进 origin/main，但分支不是 main 的祖先，
#       故 -DeleteBranch 复用上面已通过的 Test-BranchMerged 判定后用 git branch -D；
#       直接用 git branch -d 会必然误报「not fully merged」而失败（2026-09-15 修复）。
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
$merged = $false
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
    # 合并判定已通过（或显式 -Force）时用 -D：squash merge 下分支非 main 祖先，-d 的祖先校验必然失败
    $flag = if ($merged -or $Force) { "-D" } else { "-d" }
    Invoke-Git -C $root branch $flag $branch
    Write-Host "[ok] 已删除本地分支 $branch（$flag）" -ForegroundColor Green
}

Write-Host "[ok] 已移除 worktree $dir" -ForegroundColor Green
