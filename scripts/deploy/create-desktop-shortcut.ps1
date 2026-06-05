# 在桌面创建 EMSXView 快捷图标
# 只需运行一次：powershell -File create-desktop-shortcut.ps1

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$shortcutPath = Join-Path $desktopPath "EMSXView Trading.lnk"

$WshShell   = New-Object -ComObject WScript.Shell
$shortcut   = $WshShell.CreateShortcut($shortcutPath)

# 指向 wscript.exe（静默执行 VBS，不弹 PowerShell 黑框）
$shortcut.TargetPath     = "wscript.exe"
$shortcut.Arguments      = """$ProjectRoot\scripts\deploy\launch-emsxview.vbs"""
$shortcut.WorkingDirectory = $ProjectRoot
$shortcut.Description    = "启动 EMSXView Trading Platform"
$shortcut.WindowStyle    = 7   # 最小化启动

# 使用 Bloomberg 可执行文件的图标（如果存在），否则使用浏览器图标
$bbTerminal = "C:\blp\bbcomm\bbterm.exe"
$chromePath = (Get-ItemProperty "HKCU:\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice" -ErrorAction SilentlyContinue).ProgId
if (Test-Path $bbTerminal) {
    $shortcut.IconLocation = "$bbTerminal,0"
} else {
    $shortcut.IconLocation = "C:\Windows\System32\shell32.dll,14"  # 地球/网络图标
}

$shortcut.Save()

Write-Host "桌面快捷方式已创建: $shortcutPath" -ForegroundColor Green
Write-Host "双击 'EMSXView Trading' 图标即可一键启动！" -ForegroundColor Cyan
