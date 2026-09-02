# wt-new.ps1 — 新任务：fetch + 创建 worktree + 独立分支（基于 origin/main）+ 复制 .env
# 用法: ./scripts/devtools/wt-new.ps1 <task> [-Branch <分支名>] [-Base origin/main] [-Detach]
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)][string]$Task,
    [string]$Branch = "",
    [string]$Base = "origin/main",
    [switch]$Detach
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

# 任务名用作目录名成分，仅允许安全字符
if ($Task -notmatch "^[A-Za-z0-9][A-Za-z0-9._-]*$") { throw "任务名仅允许字母/数字/._-（收到: $Task）" }

$branch = if ($Branch) { $Branch } else { $Task }
$dir = Join-Path (Split-Path $root -Parent) "EMSXView-wt-$Task"
if (Test-Path $dir) { throw "目录已存在: $dir" }

Invoke-Git -C $root fetch origin --prune --quiet
if ($Detach) {
    Invoke-Git -C $root worktree add --detach $dir $Base
}
else {
    Invoke-Git -C $root worktree add -b $branch $dir $Base
}

# 复制根 .env（存在时）；子目录级忽略文件需手动复制
$envSrc = Join-Path $root ".env"
if (Test-Path $envSrc) {
    Copy-Item $envSrc (Join-Path $dir ".env")
    Write-Host "[ok] 已复制根 .env（子目录级忽略文件请手动复制）" -ForegroundColor Green
}

Write-Host ""
Write-Host "[ok] worktree 已创建: $dir" -ForegroundColor Green
if (-not $Detach) { Write-Host "     分支: $branch（基于 $Base）" }
Write-Host "后续步骤："
Write-Host "  1. cd $dir"
Write-Host "  2. 安装依赖：frontend -> npm install；backend -> pip install -r backend/api/requirements.txt"
Write-Host "  3. 并行运行请错开端口：API_PORT=3100、前端 npx vite --port 5273、VITE_API_URL=http://localhost:3100"
Write-Host "  4. 在该目录打开独立 IDE/Agent 窗口；完整规范见 docs/spec/git-workflow.md"
