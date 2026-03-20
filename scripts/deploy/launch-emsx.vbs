' ============================================================
' EMSX Trading Platform - One-Click Launcher
' 双击此文件即可启动，无需任何其他操作
' 1. 在后台启动 Python 后端（Bloomberg EMSX 连接）
' 2. 在后台启动 Vite 前端开发服务器
' 3. 等待服务就绪后自动打开浏览器
' ============================================================

Set WshShell = CreateObject("WScript.Shell")

' ---- 启动后端（完全隐藏窗口）----
WshShell.Run "powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass " & _
    "-File ""C:\Users\hrchen\Documents\EMSX\scripts\deploy\start-backend.ps1""", 0, False

' ---- 等待后端就绪（Bloomberg 连接约 3 秒）----
WScript.Sleep 6000

' ---- 启动前端 Vite 服务器（完全隐藏窗口）----
WshShell.Run "powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass " & _
    "-File ""C:\Users\hrchen\Documents\EMSX\scripts\deploy\start-frontend.ps1""", 0, False

' ---- 等待 Vite 编译完成 ----
WScript.Sleep 7000

' ---- 打开浏览器 ----
WshShell.Run "http://localhost:5173"

Set WshShell = Nothing
