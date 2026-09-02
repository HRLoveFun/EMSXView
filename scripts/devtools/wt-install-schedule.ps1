# wt-install-schedule.ps1 — 注册/卸载 Windows 计划任务：工作日 09:00 自动执行 wt-sync.ps1 每日同步
# 用法: .\scripts\devtools\wt-install-schedule.ps1 [-Uninstall]
# 任务名: EMSXView-DailyWorktreeSync；日志: logs/wt-sync-daily.log（logs/ 已被 .gitignore 覆盖）
[CmdletBinding()]
param([switch]$Uninstall)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "wt-common.ps1")

$taskName = "EMSXView-DailyWorktreeSync"

# 卸载：任务不存在时静默跳过
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "[ok] 已卸载计划任务 $taskName" -ForegroundColor Green
    }
    else {
        Write-Host "[skip] 计划任务 $taskName 不存在"
    }
    return
}

$root = Find-EmsxviewRoot
Assert-ProjectRootValid -Root $root

# 经 cmd 包装将 wt-sync 输出追加到日志文件
$logDir = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir "wt-sync-daily.log"
$wtSync = Join-Path $PSScriptRoot "wt-sync.ps1"
$action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c powershell -NoProfile -ExecutionPolicy Bypass -File `"$wtSync`" >> `"$logFile`" 2>&1"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9am
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "EMSXView Git worktree 每日同步（fetch + rebase origin/main，未提交自动跳过）" | Out-Null

Write-Host "[ok] 已注册计划任务 $taskName（工作日 09:00，日志: $logFile）" -ForegroundColor Green
Write-Host "     查看: taskschd.msc | 卸载: .\scripts\devtools\wt-install-schedule.ps1 -Uninstall"
