# 016 — wt 工具链加固（收尾可恢复 + Windows PowerShell 5.1 编码兼容）

> 特性：`016-wt-finish-robustness`
> 分支：`016-wt-finish-robustness`（worktree `../EMSXView-wt-016-wt-finish-robustness`）
> 定位：P0「作业地基」第 3 项

---

## 1. 问题一：`wt-finish.ps1` 收尾失败不可恢复（两次实测）

`specs/012`、`specs/013` 两次收尾都出现同一现象：

```
Exception: git -C <main> worktree remove <wt> 执行失败 (exit=255)
```

特征是**注册表已注销、目录残留**：`git worktree remove` 先注销 worktree，再递归删除目录；
只要目录内有文件被占用，删除失败但注销已完成。原脚本此时直接 `throw`，导致：

1. **git 的真实报错被异常信息淹没** —— 只能看到 `退出失败 (exit=255)`，看不到
   `error: failed to delete '<path>': Invalid argument`，根因不可见（两次都靠手工重跑原命令才发现）；
2. **后续步骤全部中断** —— 本地分支不会被删除，`worktree prune` 也不执行；
3. 两次都由人工删目录 + 手工删分支才收工。

### 复现与根因（本次已确定性复现）

用**独占文件句柄**（`FileShare.None`）占住 worktree 内一个文件，即复现：

```
[warn] git worktree remove 失败 (exit=255)
       error: failed to delete 'C:/Users/hrchen/Documents/EMSXView-wt-probeB': Invalid argument
```

即：目录内文件被进程占用（dev server / 测试进程 / `node_modules`、`.vite` 句柄未释放）→
递归删除 `Invalid argument` → git 以 255 退出，但注册表已注销。

## 2. 问题二：PS 脚本在 Windows PowerShell 5.1 下解析失败（本次发现）

排查问题一时发现：`scripts/**` 下 12 个 `.ps1` 为 **UTF-8 无 BOM + 含中文**。
Windows PowerShell 5.1 对无 BOM 文件按 ANSI(cp1252) 解码，中文多字节被误解析 ——
字节 `0x93`/`0x94` 在 cp1252 中是智能引号 `“`/`”`，而 PowerShell 视其为字符串定界符，
字符串字面量提前结束 ⇒ `ParserError`。实测：

| 宿主 | `wt-list.ps1` | `wt-new.ps1` |
|---|---|---|
| PowerShell Core 7.6 | 正常 | 正常 |
| Windows PowerShell 5.1 | `Missing '=' operator after key in hash literal` | `The string is missing the terminator` |

**影响面**（不是理论风险）：

- `wt-install-schedule.ps1` 注册的每日同步任务以 `cmd /c powershell ... -File wt-sync.ps1` 调用
  → 宿主是 **5.1** ⇒ 每日 worktree 同步一直在解析失败（日志里是 ParseError，不是「无改动」）；
- `.bat` 启动器（`relaunch_service.bat` / `start-all.bat` / `restart-all.bat` / `check-status.bat`）以
  `powershell -File scripts\ops\service-manager.ps1` 调用 → 同为 5.1；
- `scripts/deploy/launch-emsxview.ps1` 用 `Start-HiddenScript`（`$psi.FileName = 'powershell.exe'`）拉起
  `start-backend.ps1` / `start-frontend.ps1` → 同为 5.1。

> 说明：`launch-emsxview.ps1`、`create-desktop-shortcut.ps1`、`setup-windows.ps1` 此前已有 BOM，故未暴露；
> 无 BOM 的那批长期只在 Core 下被手动执行，问题被掩盖。

## 3. 改动

| # | 文件 | 改动 |
|---|---|---|
| 1 | `scripts/devtools/wt-common.ps1` | 新增 `Invoke-GitSoft`（不抛异常，返回 ExitCode + 合并后的 stdout/stderr），使 git 真实报错可被上层打印 |
| 2 | `scripts/devtools/wt-finish.ps1` | 新增 `Remove-WorktreeDir`：失败时区分「仍在注册表」（保留保护，提示 `-Force`）与「已注销、目录残留」（prune + 提示人工清理）；**目录残留不再阻断分支删除**；结尾以退出码 0/1 明确表态 |
| 3 | `scripts/**/*.ps1`（12 个） | 补 UTF-8 BOM（字节级，内容不变） |
| 4 | `backend/api/tests/boundaries/test_ps1_encoding.py` | 新增守卫：含非 ASCII 的 `.ps1` 必须带 BOM（规则 ID `PS1-ENC`）+ 全部 `.ps1` 可按 UTF-8 解码 |
| 5 | `.codebuddy/rules/coding-style.md` | 新增「PowerShell / 运维脚本专项」规则 |
| 6 | `docs/spec/git-workflow.md` §3.4 | 记录「注册表已注销、目录删不掉」的处置方式 |
| 7 | `specs/016-wt-finish-robustness/plan.md` | 本文件 |

## 4. 验证（全部实测）

| 项 | 结果 |
|---|---|
| 正常路径 | probe worktree → `wt-finish -Force -DeleteBranch` → **exit 0**、目录已删、分支已删 |
| 故障路径（独占文件句柄复现） | **exit 1**；打印 git 真实报错 `failed to delete ...: Invalid argument`；`prune` 已执行；**分支已删**；目录残留并打印 `Remove-Item -Recurse -Force '<dir>'` |
| 5.1 解析 `wt-list.ps1` | 修复前 `Missing '=' operator...` → 修复后**正常输出表格** |
| 5.1 解析 `wt-sync.ps1`（计划任务那支） | `PARSE_OK` |
| 5.1 运行 `wt-finish.ps1 <不存在任务>` | 报**运行时**错误（中文正常），非解析错误 |
| Core 回归 | `wt-list.ps1` 正常；测试脚本全绿 |
| 守卫测试 | `pytest backend/api/tests/boundaries/`（含新 `PS1-ENC`）；`scripts/audit_cross_imports.py`；`scripts/audit_doc_drift.py` |

## 5. 本次不做

- **不自动递归删除残留目录**：破坏性动作永不自动（`docs/spec/git-workflow.md` §9/§10），脚本只给命令。
- **不改计划任务宿主**（不切 `pwsh`）：BOM 修复已使其在 5.1 下可用，且 `powershell` 是各机器都有的宿主。
- **不重写任何脚本逻辑**（除 wt-finish 的收尾路径外）：BOM 仅改文件头 3 字节。

## 6. 顺带发现（不改动，供后续处置）

- 同级目录存在**孤儿目录** `EMSXView-wt-p2-first-batch`（非 git 仓库、无 `.git`），
  是 `wt-clean.ps1` dry-run 报 `not a git repository` 的来源。它不属于本任务，未触碰；
  建议由该任务所属会话或 `./scripts/devtools/wt-clean.ps1 -Apply` 处置。
- `wt-clean.ps1` / `wt-sync.ps1` 遍历同级目录时未跳过非 git 目录，会打印噪声错误 —— 属独立小项。

## 7. 回退

单一提交，`git revert` 即回到「wt-finish 抛异常 + 无 BOM」形态。
