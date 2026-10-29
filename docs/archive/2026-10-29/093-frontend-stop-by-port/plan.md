# 093 — 修复 restart 无法停止前端（vite 进程按端口识别）

> 触发：2026-10-27 用户执行一键重启，日志报 `Port 5173 is already in use by process: node (PID: 180108)`，退出码 1
> 分支：`093-frontend-stop-by-port`

## 1. 问题（是什么）

`service-manager.ps1` 的 `Stop-FrontendService` 只按命令行匹配：

```powershell
$_.CommandLine -like "*vite*" -and $_.CommandLine -like "*\frontend*"
```

但 npm 的 `.bin` shim 启动 vite 时，进程命令行是：

```
"node" "C:\...\EMSXView\node_modules\.bin\..\vite\bin\vite.js"
```

**不含 `\frontend`** → stop 阶段「报成功但没杀」，start 阶段端口仍被占用 → restart 失败。状态检测（`Get-ServiceStatus`）同一条件，也会漏报 `Running=False`。

## 2. 方案（为什么这样做）

- **端口监听者优先**：前端进程的权威判据是「谁在监听 5173」，用既有 `Get-ProcessUsingPortListening` 直接定位，与命令行形态无关；
- **命令行兜底**：未监听端口的 vite 残留（dev 崩了但进程还在），匹配条件放宽为含 `vite` 且命令行含 `\frontend` 或 `EMSXView`；
- **停止后等端口释放**（最多 10 秒），避免紧接着的 start 仍报占用；
- 状态检测同步改为「端口在用或有进程」即 `Running=True`。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `scripts/ops/service-manager.ps1` | 改 | `Stop-FrontendService` 端口优先 + 命令行兜底 + 等待释放；`Get-ServiceStatus` 前端段同步 |
| 2 | `specs/093-frontend-stop-by-port/plan.md` | 新增 | 本文件 |

## 4. 验收（本机实测）

1. 复现：用户日志 `Port 5173 is already in use`，占用者命令行确认为 `node ...vite/bin/vite.js`（无 `\frontend`）；
2. 修复后 `service-manager.ps1 stop -Environment dev` 输出 `Stopped frontend listener on port 5173 (PID: 159124, node)`，`Get-NetTCPConnection` 确认端口释放；
3. 随后 `restart -Environment dev` 退出码 0，后端 `Startup Phase: ready`、前端 `Frontend started successfully on port 5173`；
4. 脚本 UTF-8 BOM + AST 解析通过。
