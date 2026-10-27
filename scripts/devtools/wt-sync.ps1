# wt-sync.ps1 — 每日同步：对指定（或全部）worktree 执行 fetch + rebase origin/main
# 用法: ./scripts/devtools/wt-sync.ps1 [task]    （task 省略则同步全部 worktree）
[CmdletBinding()]
param([Parameter(Position = 0)][string]$Task = "")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

Invoke-Git -C $root fetch origin --prune --quiet

# 每日顺带清理残留目录（孤儿 + 缓存目录；含句柄处置），失败只告警不改变 sync 退出码
$gcScript = Join-Path $PSScriptRoot "wt-gc.ps1"
if (Test-Path -LiteralPath $gcScript) {
    try {
        & $gcScript -Apply -KillHolders -Quiet | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Host "[warn] wt-gc 仍有残留目录，详见 logs/wt-gc-report.json" -ForegroundColor Yellow }
    }
    catch { Write-Host "[warn] wt-gc 执行失败：$($_.Exception.Message)" -ForegroundColor Yellow }
}

$targets = Get-WtSyncTargets -Root $root -Task $Task
if (-not $targets -or $targets.Count -eq 0) {
    if ($Task) { throw "未找到匹配的 worktree（Task=$Task）。用 wt-list.ps1 查看现有 worktree" }
    # 全量模式且当前无活跃 worktree 属正常收尾状态：残留已在上面清理，直接成功退出
    Write-Host "[info] 当前无活跃 worktree，跳过同步（已完成残留清理）"
    exit 0
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
