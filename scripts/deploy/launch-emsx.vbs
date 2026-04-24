' ============================================================
' EMSX Trading Platform - One-Click Launcher (Robust Version)
' 双击此文件即可启动，无需任何其他操作
' 1. 并行启动 Python 后端和 Vite 前端
' 2. 前端就绪后立即打开浏览器，不再被后端 60s 等待阻塞
' 3. 后端继续在后台等待就绪；失败时再显示诊断页面
' 4. 启动失败时在浏览器中显示错误诊断页面
' ============================================================

Set WshShell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

Const BACKEND_PORT    = 3000
Const FRONTEND_PORT   = 5173
Const POLL_INTERVAL   = 1000      ' 每 1 秒检测一次
Const BACKEND_TIMEOUT   = 60000   ' 后端最多等 60 秒
Const FRONTEND_TIMEOUT  = 120000  ' 前端最多等 120 秒
Const EMSX_ROOT        = "C:\Users\hrchen\Documents\EMSX"
Dim ERROR_PAGE_PATH
ERROR_PAGE_PATH  = EMSX_ROOT & "\logs\startup-error.html"
Dim FRONTEND_OPENED
FRONTEND_OPENED = False

' ---- 并行启动后端与前端（完全隐藏窗口）----
WshShell.Run "powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass " & _
    "-File """ & EMSX_ROOT & "\scripts\deploy\start-backend.ps1""", 0, False
WshShell.Run "powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass " & _
    "-File """ & EMSX_ROOT & "\scripts\deploy\start-frontend.ps1""", 0, False

' ---- 前端优先就绪并打开浏览器 ----
If Not WaitForPort(FRONTEND_PORT, FRONTEND_TIMEOUT, "Frontend") Then
    ShowErrorPage "Frontend", FRONTEND_PORT, FRONTEND_TIMEOUT, Array( _
        "node_modules 未安装（在 ExecutionView/frontend/ 下运行 npm install）", _
        "端口 5173 被其他程序占用（上次运行未正确关闭）", _
        "Node.js / npm 未安装或不在 PATH 中", _
        "npm SSL 证书问题（运行 npm config set strict-ssl false）" _
    ), False
    WScript.Quit 1
End If

WshShell.Run "http://localhost:" & FRONTEND_PORT
FRONTEND_OPENED = True

' ---- 后端继续在后台等待，不阻塞前端打开 ----
If Not WaitForPort(BACKEND_PORT, BACKEND_TIMEOUT, "Backend") Then
    ShowErrorPage "Backend", BACKEND_PORT, BACKEND_TIMEOUT, Array( _
        "Python 环境未找到（检查 D:\anaconda3\python.exe 是否存在）", _
        "端口 3000 被其他程序占用（上次运行未正确关闭）", _
        "依赖包缺失（在 ExecutionView/backend/ 下运行 pip install）", _
        "Bloomberg BPIPE 连接失败（检查 Terminal 是否在线）" _
    ), FRONTEND_OPENED
    WScript.Quit 1
End If

Set WshShell = Nothing
Set fso = Nothing
WScript.Quit 0

' ============================================================
' 生成错误诊断 HTML 页面并在浏览器中打开
' ============================================================
Sub ShowErrorPage(serviceName, port, timeoutMs, possibleCauses, frontendOpened)
    Dim html, ts, logHint, frontendHint

    ' 尝试读取最近日志
    logHint = ""
    Dim logDir
    Set logDir = fso.GetFolder(EMSX_ROOT & "\logs")
    If logDir.Files.Count > 0 Then
        Dim latestLog, latestDate, f
        Set latestLog = Nothing
        latestDate = #1/1/1970#
        For Each f In logDir.Files
            If LCase(f.Name) <> LCase(fso.GetFileName(ERROR_PAGE_PATH)) Then
                If DateDiff("s", latestDate, f.DateLastModified) > 0 Then
                    Set latestLog = f
                    latestDate = f.DateLastModified
                End If
            End If
        Next
        If Not latestLog Is Nothing Then
            logHint = "  <p>最新日志文件: <code>" & latestLog.Name & "</code> (" & latestLog.DateLastModified & ")</p>" & vbCrLf
            On Error Resume Next
            Dim logFile, logContent, lines, lineCount
            Set logFile = fso.OpenTextFile(latestLog.Path, 1, False)
            If Err.Number = 0 Then
                logContent = logFile.ReadAll
                logFile.Close
                lines = Split(logContent, vbCrLf)
                If UBound(lines) >= 0 Then
                    lineCount = UBound(lines) + 1
                    Dim startLine, tailLines, i, lineHtml
                    startLine = 0
                    If lineCount > 30 Then startLine = lineCount - 30
                    tailLines = ""
                    For i = startLine To UBound(lines)
                        tailLines = tailLines & ServerHTMLEncode(lines(i)) & vbCrLf
                    Next
                    logHint = logHint & "  <details><summary>查看最近 " & (UBound(lines) - startLine + 1) & " 行日志</summary>" & vbCrLf & _
                        "  <pre>" & tailLines & "</pre>" & vbCrLf & _
                        "  </details>" & vbCrLf
                End If
            End If
            On Error GoTo 0
        End If
    End If

    ' 检查端口占用
    Dim portCheck
    portCheck = ""
    Set oExec = WshShell.Exec("netstat -ano | findstr :" & port)
    If Not oExec.StdOut.AtEndOfStream Then
        portCheck = "  <div class='warning'>⚠ 端口 " & port & " 当前被占用:<pre>" & ServerHTMLEncode(oExec.StdOut.ReadAll()) & "</pre></div>" & vbCrLf
    End If

    frontendHint = ""
    If frontendOpened Then
        frontendHint = "  <div class='warning'>ℹ 前端已经打开：<code>http://localhost:" & FRONTEND_PORT & "</code>。你可以先在页面内等待 backend 就绪，同时参考此诊断页继续排查。</div>" & vbCrLf
    End If

    ' 生成 HTML
    html = "<!DOCTYPE html>" & vbCrLf & _
        "<html lang='zh-CN'>" & vbCrLf & _
        "<head>" & vbCrLf & _
        "<meta charset='UTF-8'>" & vbCrLf & _
        "<title>EMSX - " & serviceName & " 启动失败</title>" & vbCrLf & _
        "<style>" & vbCrLf & _
        "* { margin: 0; padding: 0; box-sizing: border-box; }" & vbCrLf & _
        "body { font-family: -apple-system, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex; align-items: center; justify-content: center; }" & vbCrLf & _
        ".card { background: #1e293b; border-radius: 16px; padding: 40px; max-width: 640px; width: 90%; box-shadow: 0 25px 50px rgba(0,0,0,0.4); }" & vbCrLf & _
        ".icon { font-size: 64px; margin-bottom: 16px; }" & vbCrLf & _
        "h1 { color: #f87171; font-size: 24px; margin-bottom: 8px; }" & vbCrLf & _
        ".subtitle { color: #94a3b8; margin-bottom: 24px; font-size: 14px; }" & vbCrLf & _
        "h2 { color: #fbbf24; font-size: 16px; margin: 20px 0 12px; }" & vbCrLf & _
        "ul { padding-left: 20px; margin-bottom: 20px; }" & vbCrLf & _
        "li { color: #cbd5e1; margin-bottom: 8px; font-size: 14px; line-height: 1.6; }" & vbCrLf & _
        "code { background: #334155; padding: 2px 6px; border-radius: 4px; font-size: 13px; color: #7dd3fc; }" & vbCrLf & _
        "pre { background: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 16px; margin: 12px 0; overflow: auto; max-height: 300px; font-size: 12px; color: #94a3b8; white-space: pre-wrap; }" & vbCrLf & _
        "details { margin: 12px 0; }" & vbCrLf & _
        "summary { cursor: pointer; color: #7dd3fc; font-size: 14px; }" & vbCrLf & _
        "summary:hover { text-decoration: underline; }" & vbCrLf & _
        ".warning { background: #422006; border: 1px solid #92400e; border-radius: 8px; padding: 16px; margin: 16px 0; }" & vbCrLf & _
        ".actions { display: flex; gap: 12px; margin-top: 24px; flex-wrap: wrap; }" & vbCrLf & _
        ".btn { padding: 10px 20px; border: none; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 600; text-decoration: none; display: inline-block; }" & vbCrLf & _
        ".btn-primary { background: #3b82f6; color: white; }" & vbCrLf & _
        ".btn-primary:hover { background: #2563eb; }" & vbCrLf & _
        ".btn-secondary { background: #334155; color: #e2e8f0; }" & vbCrLf & _
        ".btn-secondary:hover { background: #475569; }" & vbCrLf & _
        ".footer { color: #475569; font-size: 12px; margin-top: 24px; padding-top: 16px; border-top: 1px solid #334155; }" & vbCrLf & _
        "</style>" & vbCrLf & _
        "</head>" & vbCrLf & _
        "<body>" & vbCrLf & _
        "<div class='card'>" & vbCrLf & _
        "  <div class='icon'>🚫</div>" & vbCrLf & _
        "  <h1>EMSX " & serviceName & " 启动失败</h1>" & vbCrLf & _
        "  <p class='subtitle'>服务在 " & (timeoutMs / 1000) & " 秒内未能就绪 (localhost:" & port & ")</p>" & vbCrLf & _
        frontendHint & _
        portCheck & _
        "  <h2>可能的原因</h2>" & vbCrLf & _
        "  <ul>" & vbCrLf

    Dim cause
    For Each cause In possibleCauses
        html = html & "    <li>" & cause & "</li>" & vbCrLf
    Next

    html = html & _
        "  </ul>" & vbCrLf & _
        "  <h2>日志信息</h2>" & vbCrLf & _
        logHint & _
        "  <h2>快速修复</h2>" & vbCrLf & _
        "  <ul>" & vbCrLf & _
        "    <li>打开 PowerShell，运行 <code>cd " & EMSX_ROOT & "\scripts</code> 然后 <code>.\stop-all.bat</code> 停止残留进程</li>" & vbCrLf & _
        "    <li>用 <code>start-services.bat</code> 可见窗口模式启动，查看具体报错</li>" & vbCrLf & _
        "  </ul>" & vbCrLf & _
        "  <div class='actions'>" & vbCrLf & _
        "    <a class='btn btn-primary' href='file:///" & Replace(ERROR_PAGE_PATH, "\", "/") & "' onclick='location.reload()'>刷新重试</a>" & vbCrLf & _
        "    <a class='btn btn-secondary' href='http://localhost:" & port & "'>重新连接</a>" & vbCrLf & _
        "  </div>" & vbCrLf & _
        "  <div class='footer'>" & vbCrLf & _
        "    EMSX Trading Platform &middot; " & Now() & vbCrLf & _
        "  </div>" & vbCrLf & _
        "</div>" & vbCrLf & _
        "</body>" & vbCrLf & _
        "</html>"

    ' 确保目录存在
    If Not fso.FolderExists(EMSX_ROOT & "\logs") Then
        fso.CreateFolder EMSX_ROOT & "\logs"
    End If

    ' 写入文件
    Dim htmlFile
    Set htmlFile = fso.CreateTextFile(ERROR_PAGE_PATH, True)
    htmlFile.Write html
    htmlFile.Close

    ' 在浏览器中打开
    WshShell.Run "file:///" & Replace(ERROR_PAGE_PATH, "\", "/")
End Sub

' ============================================================
' 简单的 HTML 转义
' ============================================================
Function ServerHTMLEncode(str)
    Dim result
    result = str
    result = Replace(result, "&", "&amp;")
    result = Replace(result, "<", "&lt;")
    result = Replace(result, ">", "&gt;")
    result = Replace(result, """", "&quot;")
    ServerHTMLEncode = result
End Function

' ============================================================
' 轮询检测端口是否就绪
' ============================================================
Function WaitForPort(port, timeoutMs, serviceName)
    Dim elapsed
    elapsed = 0
    Do While elapsed < timeoutMs
        If IsPortOpen(port) Then
            WaitForPort = True
            Exit Function
        End If
        WScript.Sleep POLL_INTERVAL
        elapsed = elapsed + POLL_INTERVAL
    Loop
    WaitForPort = False
End Function

' ============================================================
' 检测端口是否可连接（HTTP 探测）
' ============================================================
Function IsPortOpen(port)
    On Error Resume Next
    Dim http
    Set http = CreateObject("MSXML2.ServerXMLHTTP.6.0")
    If Err.Number <> 0 Then
        IsPortOpen = False
        Err.Clear
        On Error GoTo 0
        Exit Function
    End If
    http.Open "GET", "http://localhost:" & port & "/", False
    http.setTimeouts 500, 500, 500, 500
    http.send
    If Err.Number = 0 Then
        IsPortOpen = (http.Status > 0)
    Else
        IsPortOpen = False
        Err.Clear
    End If
    On Error GoTo 0
    Set http = Nothing
End Function
