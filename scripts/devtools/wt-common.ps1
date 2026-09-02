# wt-common.ps1 — worktree 辅助脚本共享函数库（被 wt-*.ps1 dot-source，勿直接执行）

# 定位仓库根：从脚本所在目录向上查找 .emsxview-root marker（禁止硬编码层数，见 AP-16）
function Find-EmsxviewRoot {
    $current = $PSScriptRoot
    while ($current) {
        if (Test-Path (Join-Path $current ".emsxview-root")) { return $current }
        $parent = Split-Path $current -Parent
        if ($parent -eq $current) { return $null }
        $current = $parent
    }
    return $null
}

# 校验仓库根有效性：必须存在且为 git 仓库
function Assert-ProjectRootValid {
    param([string]$Root)
    if (-not $Root) { throw "未找到 .emsxview-root marker，请在 EMSXView 仓库内执行本脚本" }
    if (-not (Test-Path (Join-Path $Root ".git"))) { throw "路径 $Root 不是 git 仓库根" }
}

# 执行 git 命令，非零退出码时抛异常（输出透传到控制台）
function Invoke-Git {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    & git @GitArgs
    if ($LASTEXITCODE -ne 0) { throw "git $($GitArgs -join ' ') 执行失败 (exit=$LASTEXITCODE)" }
}

# 校验引用（本地或远程）是否存在
function Test-RefExists {
    param([string]$Root, [string]$Ref)
    & git -C $Root rev-parse --verify --quiet "$Ref" | Out-Null
    return ($LASTEXITCODE -eq 0)
}

# 解析 git worktree list --porcelain 为对象列表
function Get-WtEntries {
    param([string]$Root)
    $raw = & git -C $Root worktree list --porcelain
    $entries = @()
    $entry = $null
    foreach ($line in $raw) {
        if ($line -like "worktree *") {
            if ($entry) { $entries += $entry }
            $entry = [pscustomobject]@{ Path = $line.Substring(9); Head = ""; Branch = ""; Detached = $false; Bare = $false }
        }
        elseif ($entry) {
            if ($line -like "HEAD *") { $entry.Head = $line.Substring(5) }
            elseif ($line -like "branch *") { $entry.Branch = $line.Substring(7) -replace "^refs/heads/", "" }
            elseif ($line -eq "detached") { $entry.Detached = $true }
            elseif ($line -eq "bare") { $entry.Bare = $true }
        }
    }
    if ($entry) { $entries += $entry }
    return $entries
}

# 按任务名解析目标 worktree：Task 为空返回全部非 bare worktree
function Get-WtSyncTargets {
    param([string]$Root, [string]$Task = "")
    $all = Get-WtEntries -Root $Root | Where-Object { -not $_.Bare }
    if (-not $Task) { return $all }
    $expected = "EMSXView-wt-$Task"
    return @($all | Where-Object { (Split-Path $_.Path -Leaf) -eq $expected })
}

# 分支是否已合并进 origin/main（is-ancestor 或 squash 后 git cherry 无 "+" 行）
function Test-BranchMerged {
    param([string]$Root, [string]$Branch)
    if (-not (Test-RefExists -Root $Root -Ref "origin/main")) { throw "origin/main 不存在，请先 git fetch" }
    & git -C $Root merge-base --is-ancestor $Branch origin/main 2>$null
    if ($LASTEXITCODE -eq 0) { return $true }
    $cherry = @(& git -C $Root cherry origin/main $Branch 2>$null)
    $ahead = @($cherry | Where-Object { $_ -like "+*" })
    return ($ahead.Count -eq 0)
}
