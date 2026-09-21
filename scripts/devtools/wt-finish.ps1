# wt-finish.ps1 — 完成任务：校验分支已合并 → 移除 worktree → prune → 可选删除本地分支
# 用法: ./scripts/devtools/wt-finish.ps1 <task> [-DeleteBranch] [-Force]
# 注意: 本仓库约定 squash merge —— 分支内容已进 origin/main，但分支不是 main 的祖先，
#       故 -DeleteBranch 复用上面已通过的 Test-BranchMerged 判定后用 git branch -D；
#       直接用 git branch -d 会必然误报「not fully merged」而失败（2026-09-15 修复）。
# 另注: git cherry 的 squash 识别是**逐 commit 比对 patch-id** —— 多提交分支被 squash 后每个
#       commit 的 patch-id 都不等于合并出的那一个，会被判为未合并而保守拒绝，需确认 PR 已
#       MERGED 后加 -Force；避免之道是「一分支一提交」（docs/spec/git-workflow.md §4）。
# 加固 (2026-09-16, specs/016-wt-finish-robustness)：Windows 上 git worktree remove 可能
#       「注册表已注销、目录删不掉」（目录内文件被进程占用：dev server / 测试 / 终端 cwd /
#       node_modules 句柄）。此时不再抛裸异常中断，而是 prune + 继续删分支 + 打印清理指引。
# 指引收敛 (2026-09-21, specs/025-wt-residual-cleanup-guidance)：残留目录的清理指引由「裸
#       Remove-Item」改为仓库工具 wt-clean.ps1（它带锁保护 / 强制须指名 / _tmp 在途保护）——
#       实测该形态残留会反复出现（020/022/023/024 各一次），而裸递归删除会绕过上述保护。
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Task,
    [switch]$DeleteBranch,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

# 移除 worktree：返回 $true 表示目录已删除；$false 表示注册表已注销但目录残留（或拒绝移除）
# 失败原因与处置指引直接打印到控制台（git 自身输出不再被异常淹没）
function Remove-WorktreeDir {
    param([string]$Root, [string]$Dir, [switch]$ForceRemove)

    $removeArgs = @("worktree", "remove", $Dir)
    if ($ForceRemove) { $removeArgs += "--force" }

    $result = Invoke-GitSoft -C $Root @removeArgs
    if ($result.ExitCode -eq 0) { return $true }

    Write-Host "[warn] git worktree remove 失败 (exit=$($result.ExitCode))" -ForegroundColor Yellow
    if ($result.Output) { Write-Host "       $($result.Output)" -ForegroundColor Yellow }

    $stillRegistered = @(
        Get-WtEntries -Root $Root | Where-Object { $_.Path -eq $Dir }
    ).Count -gt 0

    if ($stillRegistered) {
        Write-Host "[fail] worktree 仍在注册表中，未做进一步处理（保护：可能存在未提交改动）" -ForegroundColor Red
        Write-Host "       确认可丢弃后重试：wt-finish.ps1 <task> -Force" -ForegroundColor Red
        return $false
    }

    # 注册表已注销、目录残留：prune 收尾后给出清理指引（递归删除属破坏性动作，不自动执行）
    Invoke-GitSoft -C $Root worktree prune | Out-Null
    Write-Host "[warn] worktree 已从注册表注销，但目录未删除：$Dir" -ForegroundColor Yellow
    Write-Host "       常见原因：目录内文件被进程占用（dev server / 测试进程 / 终端 cwd 指向该目录、" -ForegroundColor Yellow
    Write-Host "       node_modules 或 .vite 句柄未释放）。推荐用仓库工具清理（自带锁保护与指名校验）：" -ForegroundColor Yellow
    Write-Host "       ./scripts/devtools/wt-clean.ps1 $Task -Apply -Force" -ForegroundColor Yellow
    Write-Host "       （只想清目录、不动 _tmp 时加 -SkipTmp；等价裸命令：Remove-Item -Recurse -Force '$Dir'）" -ForegroundColor Yellow
    return $false
}

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

$dir = Join-Path (Split-Path $root -Parent) "EMSXView-wt-$Task"
if (-not (Test-Path $dir)) { throw "worktree 目录不存在: $dir（用 wt-list.ps1 查看现有 worktree）" }

$branch = (& git -C $dir branch --show-current)
$merged = $false
if ($branch -and -not $Force) {
    $merged = Test-BranchMerged -Root $root -Branch $branch
    if (-not $merged) {
        $pending = @(& git -C $root rev-list "origin/main..$branch").Count
        Write-Host "[fail] 分支 $branch 尚未合并进 origin/main（git cherry 判定），拒绝移除" -ForegroundColor Red
        Write-Host "       该分支相对 origin/main 有 $pending 个提交未被 patch-id 匹配。" -ForegroundColor Red
        Write-Host "       - 单提交分支：patch-id 可直接匹配，通常不会走到这里" -ForegroundColor Red
        Write-Host "       - 多提交分支：被 squash 后每个 commit 的 patch-id 都不等于合并出的那一个 → 必然拒绝" -ForegroundColor Red
        Write-Host "       确认 PR 已 MERGED 后加 -Force 重试；避免之道是「一分支一提交」（docs/spec/git-workflow.md §4）" -ForegroundColor Red
        exit 1
    }
}

$removed = Remove-WorktreeDir -Root $root -Dir $dir -ForceRemove:$Force
if ($removed) {
    Invoke-Git -C $root worktree prune
}

if ($DeleteBranch -and $branch) {
    # 合并判定已通过（或显式 -Force）时用 -D：squash merge 下分支非 main 祖先，-d 的祖先校验必然失败。
    # 目录残留不影响分支删除 —— 分支已确认合并，残留的只是文件。
    $flag = if ($merged -or $Force) { "-D" } else { "-d" }
    Invoke-Git -C $root branch $flag $branch
    Write-Host "[ok] 已删除本地分支 $branch（$flag）" -ForegroundColor Green
}

if ($removed) {
    Write-Host "[ok] 已移除 worktree $dir" -ForegroundColor Green
    exit 0
}

Write-Host "[warn] worktree 目录仍残留：$dir（按上方指引手动清理）" -ForegroundColor Yellow
exit 1
