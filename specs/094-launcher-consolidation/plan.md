# 094 — 启动脚本收敛到根目录 + 控制台中文乱码修复

> 触发：2026-10-27 用户反馈「一键重启窗口中文乱码」；随后要求「梳理重构 .bat，减少数量、统一根目录」
> 分支：`094-console-encoding`（基线 `origin/main`）

## 1. 问题

**脚本分散**：5 个入口——`scripts/{start-all,stop-all,restart-all,check-status}.bat` 四个近重复脚本 + 根目录 `relaunch_service.bat`。四个脚本内容仅差一个 action，且存在换行丢失（`echo.REM Change to script directory` 粘连）导致多余回显。

**乱码有两个独立来源**：
1. Windows PowerShell 5.1 在 `chcp 65001` 窗口里仍可能按 OEM 代码页编码输出；
2. `check-startup-status.ps1` 用 `Invoke-WebRequest.Content` 解析后端 JSON——FastAPI 返回 `application/json` **不带 charset** 时，PS 5.1 按 ISO-8859-1 解码，中文变 `BackendãBloomberg`。

## 2. 方案

**收敛**：根目录 `emsxview.bat` 作统一入口（`start|stop|restart|status`，默认 `status`，退出码透传）；删除 `scripts/` 下四个 bat；`relaunch_service.bat` 保留为双击入口（带等待前端 + 打开页面）。入口数 5 → 2。

**编码**：
- `service-manager.ps1` 入口显式 `[Console]::OutputEncoding = UTF8`（与 bat 的 `chcp 65001` 对齐）；
- `check-startup-status.ps1` 改用 `RawContentStream` 按 UTF-8 重解码再 `ConvertFrom-Json`。

## 3. 落地

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `emsxview.bat` | 新增 | 统一入口，参数校验（未知参数 exit 2） |
| 2 | `scripts/{start-all,stop-all,restart-all,check-status}.bat` | 删除 | 功能并入 emsxview.bat |
| 3 | `scripts/ops/service-manager.ps1` | 改 | 入口设 UTF-8 输出编码 |
| 4 | `scripts/diagnose/check-startup-status.ps1` | 改 | JSON 按 UTF-8 解码 |
| 5 | `AGENTS.md`、`README.md`、`QUICKSTART.md`、`docs/dev-guide.md`、`docs/ops/service-management.md`、`docs/spec/project-structure.md`、`scripts/README.md` | 改 | 命令与目录树引用 |

## 4. 验收（本机实测）

1. `emsxview.bat status` → 退出码 0，输出 `Startup Message: Backend、Bloomberg 与 EMSX 订阅…`（中文正常）；
2. `emsxview.bat bogus` → 退出码 2 + 用法提示；
3. `emsxview.bat`（无参数）等价 `status`；
4. 全仓无 `start-all.bat` / `stop-all.bat` / `restart-all.bat` / `check-status.bat` 残留引用（除 `docs/archive/` 历史文档与 `anti-patterns.md` 的事故描述）；
5. `audit_doc_drift.py` 无漂移；`test_ps1_encoding` 2 passed。
