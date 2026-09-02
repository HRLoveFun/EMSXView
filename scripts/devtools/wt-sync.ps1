# wt-sync.ps1 — 每日同步：对指定（或全部）worktree 执行 fetch + rebase origin/main
# 用法: ./scripts/devtools/wt-sync.ps1 [task]    （task 省略则同步全部 worktree）
[CmdletBinding()]
param([Parameter(Position = 0)][string]$Task = "")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

Invoke-Git -C $root fetch origin --prune --quiet

$targets = Get-WtSyncTargets -Root $root -Task $Task
if (-not $targets -or $targets.Count -eq 0) {
    throw "未找到匹配的 worktree（Task=$Task）。用 wt-list.ps1 查看现有 worktree"
}

$failed = @()
foreach ($wt in $targets) {
    $label = Split-Path $wt.Path -Leaf
    $dirty = @(& git -C $wt.Path status --porcelain).Count
    if ($dirty -gt 0) {
        Write-Host "[skip] $label 有 $dirty 个未提交文件，请先 commit（不要用 stash）" -ForegroundColor Yellow
        continue
    }
    Write-Host "[sync] $label ($($wt.Branch)) rebase origin/main ..."
    & git -C $wt.Path rebase origin/main
    if ($LASTEXITCODE -ne 0) {
        # 冲突时自动中止恢复原状，交由人工解决
        & git -C $wt.Path rebase --abort
        $failed += $label
        Write-Host "[fail] $label rebase 冲突，已自动 abort，请手动解决后重试" -ForegroundColor Red
    }
    else {
        Write-Host "[ok]   $label" -ForegroundColor Green
    }
}

if ($failed.Count -gt 0) { exit 1 }
