' ============================================================
' EMSXView Trading Platform - Thin VBS Launcher
' ------------------------------------------------------------
' 仅作桌面快捷方式 -> PowerShell 启动器的"无黑框"垫片。
'
' 所有启动逻辑（项目根查找、端口轮询、错误页生成）均在
' launch-emsxview.ps1 中。VBS 不再做任何路径深度计算，
' 只与本 VBS 同目录下的 launch-emsxview.ps1 相邻可达，
' 彻底消除"WScript.ScriptFullName 比 $PSScriptRoot 多带文件名"
' 造成的宿主语义错位陷阱。
'
' 历史背景：之前的 VBS 通过 GetParentFolderName x2 推算项目根，
' 但因只向上 2 层而落到 scripts\ 目录，导致快捷方式每次启动都
' 找不到 start-*.ps1，120s 超时报错并以 B4 数据库清理日志冒充前端日志。
' ============================================================

Set fso = CreateObject("Scripting.FileSystemObject")
Set WshShell = CreateObject("WScript.Shell")

Dim ps1Path
ps1Path = fso.GetParentFolderName(WScript.ScriptFullName) & "\launch-emsxview.ps1"

If Not fso.FileExists(ps1Path) Then
    MsgBox "未找到启动脚本: " & ps1Path, vbCritical, "EMSXView 启动失败"
    WScript.Quit 99
End If

' 隐藏窗口、不阻塞 PowerShell 进程，桌面快捷方式立即释放 wscript.exe
WshShell.Run "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & ps1Path & """", 0, False

Set fso = Nothing
Set WshShell = Nothing
WScript.Quit 0