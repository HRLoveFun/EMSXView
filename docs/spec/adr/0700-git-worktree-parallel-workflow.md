# ADR-0700: Git Worktree 多任务并行工作流

> 状态: Accepted
> 日期: 2026-09-02
> 标签: process, workflow, documentation

## 背景 (Context)

本项目为个人多任务并行开发 + 多 AI Agent 协作的 monorepo。此前的分支管理方式存在以下痛点：

1. **单工作目录串行切换**：`git checkout` + `stash` 切换任务会打断思路，stash 在多任务间易丢失或拿错；无法同时运行多套开发服务器（backend :3000 / frontend :5173 / CostView :8002）。
2. **AI Agent 上下文污染**：多个 Agent（CodeBuddy / Claude Code / Cursor）读写同一工作目录时互相覆盖文件、git 状态混乱。
3. **分支生命周期积压**：`AGENTS.md`「当前计划」曾出现 004 / 005 等多个特性分支长期停留在「⏳ PR 合并回 main」状态——任务完成后的 rebase、合并、清理缺乏标准 SOP，分支与 `specs/<feature-id>/` 计划目录的对应关系靠口头约定。

## 决策 (Decision)

采用 **Git Worktree + 独立 Feature 分支 + 每日 rebase 主分支** 作为标准并行开发工作流，完整 SOP 固化在 [`docs/spec/git-workflow.md`](../git-workflow.md)：

1. **一任务一分支一目录**：每个任务在兄弟目录 `../EMSXView-wt-<task>` 中检出独立分支；主工作树保持干净（停在 main）。
2. **分支命名与 specs 体系对齐**：规格化特性任务分支名 = `specs/<feature-id>/` 目录名（沿用 004–008 惯例）；非规格任务用 `feat/` / `fix/` / `hotfix/` 前缀。
3. **每日同步纪律**：每个活跃任务每天至少一次 `git rebase origin/main`，用 commit 替代 stash。
4. **辅助脚本**：`scripts/devtools/wt-new|list|sync|finish.ps1` 四个 PowerShell 脚本封装高频操作（通过 `.emsxview-root` marker 定位根，遵循 AP-16）。
5. **AI Agent 隔离规则**：一个 Agent 绑定一个 worktree，禁止跨 worktree 操作文件与 refs；Agent 可在自己的分支自主 commit/push。
6. **数据零受损适配**：worktree 内 `CostView/data/` 默认为空（数据不入 git）；数据管道写入任务同一时间只允许一个 worktree 执行，或各用独立 `EMSXVIEW_DATA_DIR`。

## 后果 (Consequences)

### 正面
- 真正并行：多任务同时开发、多套服务同时运行、多 Agent 互不干扰；紧急 hotfix 不打断进行中的 feature。
- 分支 ↔ specs 目录 ↔ worktree 目录三者可互相追溯，消除「当前计划」状态积压。
- 冲突前移：每日 rebase 小步化解冲突，替代合并日大爆炸。

### 负面 / 取舍
- 每个 worktree 需独立安装依赖（`node_modules` / pip 环境）与复制忽略文件（`.env`），有一次性成本。
- 兄弟目录在项目文件夹外，多个 worktree 增加目录管理成本；需坚持「完成即清理」。
- 磁盘占用：历史共享很省，但依赖安装重复；大数据调试须依赖 `EMSXVIEW_DATA_DIR` 指向主工作树（只读）。

### 对其他 ADR 的影响
- 引用: [ADR-0012](0012-config-isolation-rule.md)（worktree 内运行参数仍以 `DataPipeline/config.py` / `.env` 为真相源）
- 引用: [ADR-0014](0014-dead-code-cleanup.md)（遵循其确立的文件放置规范：脚本归 `scripts/devtools/`，规范文档归 `docs/spec/`）
- 被引用: 未来若引入 CI 级分支保护或 PR 模板，需与本工作流的分支命名规范对齐

## 备选方案 (Considered Alternatives)

- **stash + checkout 串行切换**：未采纳。无法并行、易丢失工作、AI Agent 同目录互相污染。
- **多次 clone**：未采纳。磁盘浪费（本项目依赖与数据体量大）、远程历史不同步。
- **Worktrunk / git-wt 等第三方工具**：未采纳（暂缓）。原生 `git worktree` + 4 个薄脚本已覆盖全部高频操作，不引入额外工具链依赖；后续若有需要可再评估。

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件:
  - `docs/spec/git-workflow.md` — 完整 SOP（新增）
  - `scripts/devtools/wt-common.ps1` / `wt-new.ps1` / `wt-list.ps1` / `wt-sync.ps1` / `wt-finish.ps1` — 辅助脚本（新增）
  - `AGENTS.md` / `CODEBUDDY.md` — 必读清单 +「Git 多任务并行工作流」章节
  - `docs/spec/memory.md` — ADR 索引与关键入口（`audit_doc_drift.py` CORE 门禁要求同步）
- 配套测试: `python scripts/audit_doc_drift.py` 通过；`wt-new → wt-list → wt-sync → wt-finish` 往返冒烟测试
- 回滚策略: 流程类决策，直接停用脚本并按传统单目录方式开发即可，无代码层面回滚成本
