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
    $rows += [pscustomobject]@{
        目录   = $wt.Path
        分支   = $branchLabel
        领先   = $ahead
        落后   = $behind
        未提交 = $dirty
        备注   = $note
    }
}
$rows | Format-Table -AutoSize
