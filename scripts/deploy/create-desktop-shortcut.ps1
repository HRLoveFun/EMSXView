# 在桌面创建 EMSX 快捷图标
# 只需运行一次：powershell -File create-desktop-shortcut.ps1

$desktopPath = [System.Environment]::GetFolderPath('Desktop')
$shortcutPath = Join-Path $desktopPath "EMSX Trading.lnk"

$WshShell   = New-Object -ComObject WScript.Shell
$shortcut   = $WshShell.CreateShortcut($shortcutPath)

# 指向 wscript.exe（静默执行 VBS，不弹 PowerShell 黑框）
$shortcut.TargetPath     = "wscript.exe"
$shortcut.Arguments      = """C:\Users\hrchen\Documents\EMSX\scripts\deploy\launch-emsx.vbs"""
$shortcut.WorkingDirectory = "C:\Users\hrchen\Documents\EMSX"
$shortcut.Description    = "启动 EMSX Trading Platform"
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
Write-Host "双击 'EMSX Trading' 图标即可一键启动！" -ForegroundColor Cyan
