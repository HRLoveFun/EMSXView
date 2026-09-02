# Git 多任务并行工作流（Git Worktree SOP）

> 定位：个人多任务并行开发的标准作业流程，针对 AI Agent（CodeBuddy / Claude Code / Cursor 等）协作场景优化。
> 决策记录：[ADR-0700](adr/0700-git-worktree-parallel-workflow.md)
> 生效范围：本仓库所有分支操作、并行任务管理与 AI Agent 工作区隔离。
> Last updated: 2026-09-02

---

## 1. 核心方案与原则

**Git Worktree + 独立 Feature 分支 + 每日 rebase 主分支。**

| 原则 | 内容 |
|------|------|
| 一任务一分支一目录 | 每个任务在独立的 worktree 目录中，检出独立分支；主工作树保持干净（通常停在 main） |
| 共享历史，隔离工作区 | 所有 worktree 共享 `.git` 对象库与远程（一次 fetch 全局可见）；工作文件、index、构建产物完全隔离 |
| 频繁 rebase | 每个活跃任务**每天至少一次** `git rebase origin/main`，冲突小步化解，避免合并日"大爆炸" |
| 用 commit 替代 stash | stash 是仓库级共享的，多 worktree 下极易拿错；临时保存一律 commit 到自己分支 |
| 完成即清理 | 分支合并后立即 remove worktree、删除分支；定期 `git worktree prune` |

**为何不用 stash + checkout**：打断思路、易丢失工作、无法并行运行多个开发服务器、多个 AI Agent 同目录互相覆盖与上下文污染。
**为何不用多次 clone**：磁盘浪费、历史不同步。Worktree 创建几乎零成本（内部是指向主仓库的文本链接）。

---

## 2. 目录结构与命名规范

采用**兄弟目录**结构（不放进仓库树内，避免污染工作区与 .gitignore）：

```
Documents/
├── EMSXView/                          # 主工作树（保持干净，停在 main）
├── EMSXView-wt-009-costview-xxx/      # 规格化特性任务（分支名 = feature-id）
├── EMSXView-wt-fix-ws-reconnect/      # 非规格修复任务
├── EMSXView-wt-review-pr123/          # 临时 PR 审查
└── EMSXView-wt-experiment/            # 实验性分支（detached HEAD）
```

**命名规范（与既有 `specs/<feature-id>` 惯例对齐）**：

| 任务类型 | 分支名 | 目录名 | 示例 |
|---|---|---|---|
| 规格化特性（有 `specs/<feature-id>/` 计划） | `<feature-id>` | `EMSXView-wt-<feature-id>` | 分支 `009-costview-anomaly-detail`，目录 `EMSXView-wt-009-costview-anomaly-detail` |
| 非规格功能 | `feat/<task>` | `EMSXView-wt-<task>` | 分支 `feat/quota-dashboard` |
| 缺陷修复 | `fix/<task>` | `EMSXView-wt-<task>` | 分支 `fix/ws-reconnect` |
| 紧急修复（从 origin/main 切出） | `hotfix/<task>` | `EMSXView-wt-<task>` | 分支 `hotfix/login-crash` |
| PR 审查 | `pr-<编号>` | `EMSXView-wt-review-pr<编号>` | 分支 `pr-123` |
| 实验 | 任意（建议 detached HEAD，不留分支） | `EMSXView-wt-<name>` | — |

> 规格化任务的分支名**必须**与 `specs/<feature-id>/` 目录名一致（沿用 004–008 的既有惯例），保证 AGENTS.md「当前计划」、specs 目录、分支三者可互相追溯。

---

## 3. 快速上手（辅助脚本）

辅助脚本位于 `scripts/devtools/`（PowerShell，Windows 主力环境；每条命令均附原生 git 等价写法）。在**主工作树或任意 worktree** 中执行均可——脚本通过 `.emsxview-root` marker 自动定位仓库根。

| 脚本 | 用途 |
|------|------|
| `wt-new.ps1` | 新任务：fetch + 创建 worktree + 新分支 + 复制 `.env` |
| `wt-list.ps1` | 列出全部 worktree 及各分支领先/落后 origin/main 的提交数 |
| `wt-sync.ps1` | 每日同步：对指定（或全部）worktree 执行 `fetch + rebase origin/main` |
| `wt-finish.ps1` | 完成：校验分支已合并后移除 worktree、prune、可选删分支 |
| `wt-common.ps1` | 共享函数库（勿直接执行） |

### 3.1 新任务

```powershell
# 规格化特性任务（分支名 = feature-id，默认基于 origin/main）
./scripts/devtools/wt-new.ps1 009-costview-anomaly-detail

# 非规格任务，显式指定分支名
./scripts/devtools/wt-new.ps1 ws-reconnect -Branch fix/ws-reconnect

# 紧急 hotfix（从最新 main 切出，不影响进行中的 feature 目录）
./scripts/devtools/wt-new.ps1 login-crash -Branch hotfix/login-crash

# 临时实验（detached HEAD，不创建分支）
./scripts/devtools/wt-new.ps1 experiment -Detach
```

原生等价：

```bash
git fetch origin
git worktree add -b 009-costview-anomaly-detail ../EMSXView-wt-009-costview-anomaly-detail origin/main
cd ../EMSXView-wt-009-costview-anomaly-detail
```

脚本会自动：复制根目录 `.env`（若存在）→ 打印依赖安装与端口偏移指引（见 §6）。其余被忽略文件（如子目录级 `.env`）需手动复制。

### 3.2 每日同步

```powershell
./scripts/devtools/wt-sync.ps1                     # 同步全部活跃 worktree
./scripts/devtools/wt-sync.ps1 009-costview-anomaly-detail   # 只同步一个
```

原生等价（在 worktree 内）：`git fetch origin && git rebase origin/main`

rebase 冲突时脚本会自动 `git rebase --abort` 恢复原状并提示——请手动解决冲突后再同步。

### 3.3 状态总览

```powershell
./scripts/devtools/wt-list.ps1
```

原生等价：`git worktree list --verbose`

### 3.4 完成与清理

```powershell
./scripts/devtools/wt-finish.ps1 009-costview-anomaly-detail              # 校验已合并后移除
./scripts/devtools/wt-finish.ps1 009-costview-anomaly-detail -DeleteBranch # 同时删除本地分支
```

脚本会拒绝移除分支尚未合并进 origin/main 的 worktree（`-Force` 可强行移除，未提交改动将丢失，慎用）。

原生等价：`git worktree remove ../EMSXView-wt-xxx` → `git worktree prune` → `git branch -d <分支>`

---

## 4. 日常开发纪律

1. **小步提交**：单次 PR 建议 ≤ 200 行 diff；commit 信息用 `feat:` / `fix:` / `docs:` / `refactor:` 前缀（对齐仓库既有提交风格）。
2. **每天 rebase**：见 §3.2。优先 rebase 而非 merge，保持线性历史、PR diff 干净。
3. **及时 push**：每个任务独立 push（`git push -u origin <分支>`），进度不落单机。
4. **任务隔离**：并行任务尽量改动不同模块/文件；启动并行前评估热点文件重叠（可让 AI 分析两个任务的预计改动面）。
5. **禁止 `git push -f`**：仅允许对自己创建、确认无他人协作的分支做 force-with-lease，且需在 commit 信息说明原因。
6. **同一分支不得检出两个 worktree**（git 会直接报错）——新任务永远新建分支。
7. **合并方式**：PR 合并建议 Squash merge，保持 main 历史一行一个任务。
8. **顺序执行 git 操作**：多个 Agent 同时操作共享 refs（fetch/rebase 同一分支）易产生竞态；跨 worktree 的 git 命令串行执行。

---

## 5. 任务完成 SOP（检查清单）

- [ ] 最后一次 `wt-sync`（rebase 到最新 origin/main），跑通该任务相关测试（`pytest` / `npm test`）
- [ ] push 分支并创建 PR（Squash merge）
- [ ] PR 合并后：`wt-finish.ps1 <task> -DeleteBranch`
- [ ] 关闭对应 IDE / Agent 窗口
- [ ] 必要时更新 `AGENTS.md`「当前计划」状态与 `specs/<feature-id>/` 进度（走正常提交）

**紧急 hotfix 场景**：正在 feature 分支深挖时生产出问题——直接 `wt-new.ps1 <task> -Branch hotfix/<task>`，在全新目录修复、验证、合并；原 feature 目录的代码、运行中服务、Agent 上下文**完全不受影响**。

---

## 6. 本项目专项适配

### 6.1 数据目录隔离（★ 数据零受损）

Worktree 的工作文件是独立的，但**数据不属于 git**：

- `CostView/data/`（管道 SQLite 库，体量大）在新 worktree 中**默认为空**——这是预期行为，避免重复占用数十 GB。
- 仅做 UI / 代码调试时，可将环境变量 `EMSXVIEW_DATA_DIR` 指向主工作树的数据目录做**只读**使用：
  ```powershell
  $env:EMSXVIEW_DATA_DIR = "C:\Users\<user>\Documents\EMSXView\CostView\data"
  ```
- **禁止**两个 worktree 同时对同一数据目录执行管道写入（摄取 / 处理阶段）；数据管道类任务（S1–S5、回填、清理）同一时间只在**一个** worktree 中运行，或让各 worktree 使用独立 `EMSXVIEW_DATA_DIR`。
- 后端 `ENABLE_DB_PERSISTENCE`、`EMSXVIEW_MERGE_MODULES` 等运行参数跟随各 worktree 自己的 `.env`，互不影响。

### 6.2 端口偏移（并行运行多实例）

默认端口被占用时，给不同 worktree 分配偏移端口（后端 `API_PORT`、前端 `VITE_API_URL` 均支持环境变量 / `.env` 覆盖）：

| 服务 | 主工作树 | 第 1 个并行 worktree | 第 2 个 |
|---|---|---|---|
| backend/api | :3000 | :3100 | :3200 |
| frontend (vite) | :5173 | :5273 | :5373 |
| MarketView | :8001 | :8101 | :8201 |
| CostView | :8002 | :8102 | :8202 |

worktree 内示例（写入该 worktree 的 `.env` 或会话环境变量）：

```bash
API_PORT=3100                              # 后端
VITE_API_URL=http://localhost:3100         # 前端指向对应后端
```

前端启动：`npx vite --port 5273`（或写入 `.env` 的 `VITE_PORT`，按 vite 配置为准）。后端：`API_PORT=3100 python main.py`。

### 6.3 依赖与忽略文件

- 每个 worktree 的 `node_modules` / Python 虚拟环境**互不共享**，新建后需安装：
  ```bash
  cd frontend && npm install        # 或 npm ci
  pip install -r backend/api/requirements.txt    # 含 -e ../../platform_data
  ```
- 需要手动复制的忽略文件：根 `.env`（脚本已自动复制）、`backend/api/.env`、任何子目录级环境文件、本机密钥。
- `.githooks`（pre-commit：AGENTS.md↔CODEBUDDY.md 同步 + 质量门禁快检）依赖 `core.hookspath=.githooks`——该配置存于共享的 `.git/config`，**新 worktree 自动生效**，无需重新配置。

### 6.4 与既有流程的关系

- **specs 计划体系**：worktree 不替代 `specs/<feature-id>/plan.md` 与 G0–G3 门控；规格任务的 worktree 内应包含对应 specs 目录并在其中推进。
- **质量门禁**：pre-commit 的 `quality_gate.py --staged`、CI 的 `boundary.yml` / `audit_doc_drift.py` 对每个 worktree 的提交同等生效；hook 自动化全景见 §10。
- **文档同步门禁**：在 worktree 中编辑 `AGENTS.md` / `CODEBUDDY.md` 时，hook 同步机制照常工作；提交前确保两文件一致（规范源为 `AGENTS.md`）。

---

## 7. AI Agent 专项规则（★）

1. **一个 Agent 绑定一个 worktree**：每个 IDE 窗口 / Agent 会话只在它所在的工作目录内读写文件、执行 git 命令；禁止跨 worktree 操作文件。
2. **Agent 可自主 commit / push**：Agent 在自己的任务分支上 `git add/commit/push` 无需逐次请示，但**必须先确认当前分支**（`git branch --show-current`），禁止在 main 上直接提交功能代码。
3. **分支与目录命名遵循 §2**：Agent 创建 worktree 时不得自行发明命名；优先使用 `scripts/devtools/wt-*.ps1` 脚本而非裸命令。
4. **禁止操作其他 worktree 的 refs**：Agent 不得 checkout / rebase / 删除其他任务正在使用的分支；跨分支动作（如合并 PR 后清理）交由人或统一在主工作树执行。
5. **上下文自带规范**：新窗口的 Agent 首次进入 worktree 后，按 `AGENTS.md`「文档阅读顺序」读取规范（worktree 内文档齐全，与主工作树一致）。
6. **并行前做重叠评估**：让 AI 对比两个并行任务的预计改动文件集，重叠大（同一热点文件）时改为串行或拆分。
7. **同步状态汇报**：Agent 完成阶段性提交后，汇报分支名、领先 origin/main 的提交数、是否可合并。

---

## 8. 每日检查清单（任意一个 worktree 执行即可）

- [ ] `./scripts/devtools/wt-sync.ps1`（内部已含 `git fetch origin`）
- [ ] 处理同步输出的冲突提示
- [ ] 各任务小步提交并 push
- [ ] `./scripts/devtools/wt-list.ps1` 扫一眼：清理已完成任务的 worktree

---

## 9. 禁止事项（与 [anti-patterns](anti-patterns.md) 呼应）

| 禁止 | 原因 |
|------|------|
| 在 main 直接提交功能代码 | main 保持可发布；功能一律走任务分支 + PR |
| 多 worktree 共用一个分支 | git 直接拒绝检出；且违背任务隔离初衷 |
| 跨 worktree 用 stash 传递改动 | stash 仓库级共享，极易拿错；用 commit + cherry-pick |
| 两个 worktree 同时写同一数据目录 | 管道写入会互相破坏（见 §6.1） |
| `git push -f` 覆盖远端 | 除非明确是自己的孤立分支且已确认 |
| 把 worktree 建在仓库目录内部 | 污染工作区与 `.gitignore`；统一用兄弟目录 `../EMSXView-wt-*` |
| 长期堆积 stale worktree | 完成即清理；每月至少一次 `git worktree prune` |

---

## 10. 自动化分层（hooks + 定时任务）

自动化遵循一条总原则：**事件类用 git hooks，时间类用定时任务，破坏性动作永不自动**。

| 层 | 载体 | 覆盖场景 | 阻断性 |
|---|---|---|---|
| 事件自动化 | `.githooks/`（pre-commit / post-checkout / post-merge / pre-push） | 提交门禁、文档同步、worktree 就绪清单、依赖变更提示、main 直推保护 | 仅 pre-commit 阻断，其余提示 |
| 时间自动化 | Windows 计划任务（`wt-install-schedule.ps1` 注册，工作日 09:00）运行 `wt-sync.ps1` | 每日 fetch + rebase（未提交自动跳过、冲突自动 abort），日志 `logs/wt-sync-daily.log` | 仅快进 rebase，不清理 |
| 显式半自动 | `wt-new` / `wt-finish` | 创建 / 清理任务 | 有确认门禁（未合并拒绝移除） |
| 永不自动 | — | 删除 worktree / 分支、merge 到 main、数据管道写入、`push -f` | 必须人工确认 |

### hooks 说明

- `core.hookspath=.githooks` 存于共享的 `.git/config`，**所有 worktree 自动生效**，无需任何配置。
- `pre-commit`（已有）：`AGENTS.md`↔`CODEBUDDY.md` 同步 + `quality_gate.py --staged` 增量快检（**阻断**）。
- `post-checkout`：`git worktree add` 时输出新 worktree 就绪清单（依赖 / 端口 / 规范入口）；分支切换导致依赖清单（`package-lock.json` / 各 `requirements.txt`）变化时提示重装。非阻断。
- `post-merge`：`git pull` / merge 更新依赖清单时提示重装。非阻断。
- `pre-push`：直推 main 时提示（默认不阻断；设 `EMSXVIEW_HOOK_BLOCK_MAIN=true` 强制阻断）。
- 依赖提示默认仅打印、**不自动安装**（`npm install` / `pip install` 耗时且依赖本机环境，装错环境比漏装更糟）；如需自动安装可在 hook 中自行扩展。

### 定时同步任务

```powershell
.\scripts\devtools\wt-install-schedule.ps1             # 注册：工作日 09:00 自动同步
.\scripts\devtools\wt-install-schedule.ps1 -Uninstall  # 卸载
```

- 任务名 `EMSXView-DailyWorktreeSync`（当前用户级，无需管理员权限），可在 `taskschd.msc` 查看
- 直接复用 `wt-sync.ps1` 的全部保护逻辑：只做 rebase 快进，跳过有未提交改动的 worktree，冲突自动 abort；不清理、不 push
- 输出追加至 `logs/wt-sync-daily.log`，漏跑时下次开机自动补执行（`StartWhenAvailable`）
