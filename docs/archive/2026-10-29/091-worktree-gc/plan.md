# 091 — worktree 残留目录的主动识别与自动清理

> 父计划：`docs/spec/git-workflow.md` §3.4/§3.5（ADR-0700 多任务并行工作流）
> 分支：`091-worktree-gc`（基线 `origin/main`）
> 触发：实测残留反复出现（020/022/023/024/083/090 各一次），此前只能人工 `wt-clean <task> -Apply -Force`

## 1. 问题（是什么）

`wt-clean.ps1` 解决「怎么安全地清」，但没有解决「谁来发现、失败怎么办、如何不再复发」：

- 残留只能靠人想起来去跑 `wt-clean`，且必须逐个指名任务；
- `git worktree remove` 失败后 `wt-finish` 只打印指引，不重试、不登记，残留长期滞留；
- 句柄占用（后台 `bash` / `node` / dev server 持有 cwd）没有处置手段，人工只能重启终端；
- 没有「下次自动重试」的机制，同一目录可能残留数周（本机实测 8 个历史残留）。

## 2. 方案（为什么这样做）

新增 `wt-gc.ps1`，与 `wt-clean` 分工：**wt-clean 管「安全地删」，wt-gc 管「主动发现 + 分级 + 重试 + 登记」**。

- **主动识别**：扫描兄弟目录 `EMSXView-wt-*`，凡不在 `git worktree list` 的即孤儿；主树与仍注册的 worktree 天然排除。
- **五级分类**，只有可再生成或无内容的才自动清：

  | 分级 | 判定 | 默认动作 |
  |---|---|---|
  | `empty` | 空目录 | 自动清 |
  | `cache-only` | 顶层仅 `node_modules`/`__pycache__`/`.vite`/`dist`/`logs` 等 | 自动清 |
  | `temp-only` | 顶层仅 `_tmp` 且静置 > `-TmpMinAgeMinutes`（默认 30） | 自动清 |
  | `git-merged-clean` | 含 `.git`、无改动、分支已并入 `origin/main` | 自动清 |
  | `dirty` | 其他（含无 git 元数据的源码副本） | 需 `-Force` + 显式指名 |

- **句柄处置**：删除失败时定位占用进程，只终止白名单解释器（`bash`/`sh`/`node`/`python`/`powershell`）。命中条件两个维度互补：`CommandLine` 含目标绝对路径（首版），或**进程工作目录落在残留目录内**（2026-10-28 补齐，覆盖 `Start-Process -WorkingDirectory` 与后台解释器这类命令行不含路径的场景；`Win32_Process` 无 CWD 字段，经 `NtQueryInformationProcess` + `ReadProcessMemory` 读 PEB 的 `CurrentDirectory`，权限/架构不匹配时回落到命令行判定）。CWD 命中时排除 `powershell`/`pwsh`（交互终端的工作目录常留在 worktree 里），这类进程与 GUI/IDE、提权进程一样只登记不终止。
- **失败登记 + 下次重试**：`logs/wt-gc-report.json`（已 gitignore）记录 path/kind/attempts/killed/error；脚本每次全量扫描，天然重试。
- **三个触发点**：`wt-finish.ps1` 残留分支自动调用（单项）；`wt-sync.ps1` 每日任务末尾全量；`wt-list.ps1` 末尾只读报告。

## 3. 落地（范围锁）

| # | 文件 | 类型 | 内容 |
|---|---|---|---|
| 1 | `scripts/devtools/wt-gc.ps1` | 新增 | 识别 / 分级 / 重试 / 句柄处置 / 报告 |
| 1b | `scripts/devtools/wt-common.ps1` | 改 | 共享「命令行 / 工作目录」路径比对与进程 CWD 探测（PEB 读取） |
| 2 | `scripts/devtools/wt-finish.ps1` | 改 | 残留分支先调 wt-gc，失败再给指引 |
| 3 | `scripts/devtools/wt-sync.ps1` | 改 | 每日末尾全量 GC（失败只告警，不改退出码） |
| 4 | `scripts/devtools/wt-list.ps1` | 改 | 末尾输出残留清单 |
| 5 | `docs/spec/git-workflow.md` | 改 | 工具表 + §3.4 处置 + §3.5.1 新小节 |
| 6 | `scripts/README.md` | 改 | devtools 说明 |

## 4. 验收（本机实测）

1. 空目录 / 仅 `node_modules` / 仅 `_tmp` 三种残留：dry-run 标「可清理」，`-Apply` 全部删除；
2. 含源码且无 git 元数据的残留：标 `dirty` 并跳过，`-Force` + 指名后才删；
3. 目录被 `powershell -WorkingDirectory` 占用：无 `-KillHolders` 时失败并提示 holder 未识别；`-KillHolders` 时对命令行含路径的进程可终止并重试；
4. 真实环境一次性清理 4 个历史残留（048/054/055/056），2 个被本会话进程占用的空目录登记待重试；
5. 四个脚本 UTF-8 BOM + 语法解析通过（`test_ps1_encoding` 守卫）。
6. CWD 维度实测（2026-10-28）：目录被 `python`（工作目录在残留内、CommandLine 不含路径）占用时，`-KillHolders` 识别并终止后删除（`attempts=2 | killed=python.exe#...`）；同场景换成 `pwsh` 只输出「holder 已识别但不可自动终止：pwsh.exe#...(cwd)」并保持退出码 1，不误杀交互终端。
