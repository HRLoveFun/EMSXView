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

# 执行 git 命令并返回结果（**不抛异常**）：ExitCode + 合并后的 stdout/stderr 文本。
# 用于「失败可预期、需按退出码与输出分支处理」的场景（如 worktree remove 的句柄占用失败）——
# Invoke-Git 会在非零时抛异常，导致 git 自身的错误文本被异常信息淹没，根因不可见。
function Invoke-GitSoft {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    return [pscustomobject]@{
        ExitCode = $LASTEXITCODE
        Output   = (($output | Out-String).Trim())
    }
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

# 读取指定 worktree 的会话独占锁；无锁或不可读返回 $null
# 锁路径按工作树隔离，见 .githooks/common.sh 与 docs/spec/git-workflow.md §10
function Get-WtLockInfo {
    param([string]$Path)
    try {
        $gitDir = (& git -C $Path rev-parse --absolute-git-dir 2>$null | Select-Object -First 1)
        if (-not $gitDir) { return $null }
        $lock = Join-Path $gitDir "EMSXVIEW_SESSION_LOCK"
        if (-not (Test-Path $lock)) { return $null }
        $kv = @{}
        foreach ($line in (Get-Content $lock -ErrorAction SilentlyContinue)) {
            if ($line -match "^([^=]+)=(.*)$") { $kv[$Matches[1]] = $Matches[2] }
        }
        if (-not $kv.ContainsKey("session")) { return $null }
        $idle = "?"
        if ($kv["heartbeat"] -match "^\d+$") {
            $idle = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - [long]$kv["heartbeat"])
        }
        return [pscustomobject]@{
            Session = $kv["session"]
            Branch  = $kv["branch"]
            Host    = $kv["host"]
            IdleSec = $idle
        }
    }
    catch { return $null }
}

# 锁标识缩写（表格列宽友好）
function Format-WtLockLabel {
    param($LockInfo)
    if (-not $LockInfo) { return "-" }
    $sid = $LockInfo.Session
    if ($sid.Length -gt 12) { $sid = $sid.Substring(0, 12) + "..." }
    return "$sid ($($LockInfo.IdleSec)s)"
}

# 路径归一化到「小写 + 正斜杠 + 盘符」，兼容 Git Bash 的 /c/Users 与 Windows 的 C:\Users
function ConvertTo-MatchablePath {
    param([string]$Text)
    $t = $Text.ToLowerInvariant().Replace("\", "/")
    if ($t -match "^/([a-z])/") { $t = $t.Substring(1, 1) + ":" + $t.Substring(2) }
    return $t
}

# 判定路径是否落在（或等于）某目录之内：CWD 占用与「命令行含路径」同口径比较
function Test-PathWithin {
    param([string]$Candidate, [string]$Parent)
    if (-not $Candidate -or -not $Parent) { return $false }
    $c = ConvertTo-MatchablePath -Text $Candidate
    $p = (ConvertTo-MatchablePath -Text $Parent).TrimEnd("/")
    return ($c -eq $p) -or $c.StartsWith($p + "/")
}

# ── 进程工作目录（CWD）探测 ────────────────────────────────────────────────
# 背景：Win32_Process 没有 CWD 字段，而「工作目录落在残留目录内」的进程
# （Start-Process -WorkingDirectory、后台解释器）同样会锁住目录、使删除失败。
# 手段：NtQueryInformationProcess(ProcessBasicInformation) 取 PEB，ReadProcessMemory
# 读 RTL_USER_PROCESS_PARAMETERS.CurrentDirectory（x64 与 WOW64 两套偏移）。
# 权限不足（系统/提权进程）或宿主架构不匹配时返回 $null，调用方回落到 CommandLine 判定。

function Initialize-ProcCwdProbe {
    if ("EmsxProcCwd" -as [type]) { return $true }
    $source = @'
using System;
using System.Runtime.InteropServices;
using System.Text;

public static class EmsxProcCwd
{
    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_BASIC_INFORMATION
    {
        public IntPtr ExitStatus;
        public IntPtr PebBaseAddress;
        public IntPtr AffinityMask;
        public IntPtr BasePriority;
        public IntPtr UniqueProcessId;
        public IntPtr InheritedFromUniqueProcessId;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(int access, bool inherit, int pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(IntPtr handle, IntPtr address, byte[] buffer, int size, out IntPtr read);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool IsWow64Process(IntPtr handle, out bool wow64);

    [DllImport("ntdll.dll")]
    private static extern int NtQueryInformationProcess(IntPtr handle, int infoClass, ref PROCESS_BASIC_INFORMATION info, int length, out int returnLength);

    public static string GetWorkingDirectory(int pid)
    {
        const int PROCESS_QUERY_INFORMATION = 0x0400;
        const int PROCESS_VM_READ = 0x0010;
        IntPtr handle = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, false, pid);
        if (handle == IntPtr.Zero) { return null; }
        try
        {
            bool wow64;
            if (!IsWow64Process(handle, out wow64)) { return null; }
            // 32 位宿主无法可靠读取 64 位进程的用户态地址
            if (!wow64 && IntPtr.Size == 4) { return null; }

            PROCESS_BASIC_INFORMATION pbi = new PROCESS_BASIC_INFORMATION();
            int returned;
            int status = NtQueryInformationProcess(handle, 0, ref pbi, Marshal.SizeOf(typeof(PROCESS_BASIC_INFORMATION)), out returned);
            if (status != 0 || pbi.PebBaseAddress == IntPtr.Zero) { return null; }

            int pointerSize = wow64 ? 4 : 8;
            int paramsOffset = wow64 ? 0x10 : 0x20;   // PEB.ProcessParameters
            int curDirOffset = wow64 ? 0x24 : 0x38;   // RTL_USER_PROCESS_PARAMETERS.CurrentDirectory
            int bufferOffset = wow64 ? 4 : 8;         // UNICODE_STRING.Buffer（相对 CurrentDirectory 起始）

            IntPtr parameters = ReadPointer(handle, Offset(pbi.PebBaseAddress, paramsOffset), pointerSize);
            if (parameters == IntPtr.Zero) { return null; }

            byte[] header = new byte[pointerSize == 8 ? 16 : 8];
            IntPtr read;
            if (!ReadProcessMemory(handle, Offset(parameters, curDirOffset), header, header.Length, out read)) { return null; }
            int length = BitConverter.ToUInt16(header, 0);
            if (length <= 0 || length > 0x8000) { return null; }
            IntPtr buffer = pointerSize == 8
                ? new IntPtr(BitConverter.ToInt64(header, bufferOffset))
                : new IntPtr(BitConverter.ToInt32(header, bufferOffset));
            if (buffer == IntPtr.Zero) { return null; }

            byte[] text = new byte[length];
            if (!ReadProcessMemory(handle, buffer, text, length, out read)) { return null; }
            return Encoding.Unicode.GetString(text, 0, length);
        }
        catch (Exception)
        {
            return null;
        }
        finally
        {
            CloseHandle(handle);
        }
    }

    private static IntPtr Offset(IntPtr baseAddress, int offset)
    {
        return new IntPtr(baseAddress.ToInt64() + offset);
    }

    private static IntPtr ReadPointer(IntPtr handle, IntPtr address, int pointerSize)
    {
        byte[] buffer = new byte[pointerSize];
        IntPtr read;
        if (!ReadProcessMemory(handle, address, buffer, pointerSize, out read)) { return IntPtr.Zero; }
        return pointerSize == 8 ? new IntPtr(BitConverter.ToInt64(buffer, 0)) : new IntPtr(BitConverter.ToInt32(buffer, 0));
    }
}
'@
    try {
        Add-Type -TypeDefinition $source -ErrorAction Stop
        return $true
    }
    catch { return $false }
}

# 读取进程工作目录；不可得（权限/架构/进程已退出）返回 $null
function Get-ProcessWorkingDirectory {
    param([int]$ProcessId)
    if (-not (Initialize-ProcCwdProbe)) { return $null }
    try { return [EmsxProcCwd]::GetWorkingDirectory($ProcessId) }
    catch { return $null }
}
