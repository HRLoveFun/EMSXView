# wt-list.ps1 — 列出全部 worktree 及各分支相对 origin/main 的领先/落后/未提交状态
# 用法: ./scripts/devtools/wt-list.ps1
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root
$hasOriginMain = Test-RefExists -Root $root -Ref "origin/main"

$rows = @()
foreach ($wt in (Get-WtEntries -Root $root)) {
    if ($wt.Bare) { continue }
    $dirty = @(& git -C $wt.Path status --porcelain).Count
    $ahead = "-"
    $behind = "-"
    if ($wt.Branch -and $hasOriginMain) {
        $counts = (& git -C $root rev-list --left-right --count "origin/main...$($wt.Branch)")
        $parts = $counts -split "\s+"
        $behind = [int]$parts[0]
        $ahead = [int]$parts[1]
    }
    $note = if ($wt.Path -eq $root) { "(主工作树)" }
    elseif ($wt.Detached) { "(detached)" }
    else { "" }
    $branchLabel = if ($wt.Branch) { $wt.Branch } else { "-" }
    # 会话独占锁：持有者缩写 + 心跳静默秒数（见 docs/spec/git-workflow.md §10）
    $lockLabel = Format-WtLockLabel -LockInfo (Get-WtLockInfo -Path $wt.Path)
    $rows += [pscustomobject]@{
        目录     = $wt.Path
        分支     = $branchLabel
        领先     = $ahead
        落后     = $behind
        未提交   = $dirty
        独占锁   = $lockLabel
        备注     = $note
    }
}
$rows | Format-Table -AutoSize
