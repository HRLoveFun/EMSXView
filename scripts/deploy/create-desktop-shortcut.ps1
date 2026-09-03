# 在桌面创建 EMSXView 快捷图标
# 只需运行一次：powershell -File create-desktop-shortcut.ps1

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
# 桌面路径唯一信息源：用户 Shell 已知文件夹，避免依赖当前工作目录
$desktopPath = [Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath "EMSXView Trading.lnk"

$WshShell   = New-Object -ComObject WScript.Shell
$shortcut   = $WshShell.CreateShortcut($shortcutPath)

# 指向 wscript.exe（静默执行 VBS，不弹 PowerShell 黑框）
$shortcut.TargetPath     = "wscript.exe"
$shortcut.Arguments      = """$ProjectRoot\scripts\deploy\launch-emsxview.vbs"""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description    = "启动 EMSXView Trading Platform"
$shortcut.WindowStyle    = 7   # 最小化启动

# 使用 EMSXView 专属品牌图标（scripts/deploy/emsxview.ico，多尺寸）
$brandIcon = Join-Path $ProjectRoot "scripts\deploy\emsxview.ico"
if (Test-Path $brandIcon) {
    $shortcut.IconLocation = $brandIcon
} else {
    # 兜底：品牌图标缺失时使用系统网络图标
    $shortcut.IconLocation = "C:\Windows\System32\shell32.dll,14"  # 地球/网络图标
}

$shortcut.Save()

Write-Host "桌面快捷方式已创建: $shortcutPath" -ForegroundColor Green
Write-Host "双击 'EMSXView Trading' 图标即可一键启动！" -ForegroundColor Cyan
