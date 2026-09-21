# 019 — 残留旧路径引用清理

> 特性：`019-stale-path-references`
> 分支：`019-stale-path-references`（worktree `../EMSXView-wt-019-stale-path-references`）
> 定位：012 / 018 目录迁移的收尾；属维护性修复（无行为变更）

---

## 1. 背景

`specs/012` 与 `specs/018` 把三个业务模块从 `frontend/src/modules/` 迁至仓库根级目录
（`ExecutionView/module`、`CostView/module`、`MarketView/module`）后，**代码与 CI 全部为绿**，
但有一批「不参与编译、也不参与检测」的引用仍指向旧路径 —— 它们不会让门禁变红，
却是**下一个人照着做就会踩坑**的活文档：

- 反模式清单里的 `rg` 检测命令（照着执行 → 命中 0 文件，误以为「无违规」）；
- 上手指南 `module-onboarding.md`（照着做 → 会把新模块建到已废弃的位置）；
- 主 README 的仓库结构树与「前端入口唯一表」（照着读 → 得到错误的心智模型）；
- 个别代码 docstring / 注释里的路径。

判定原则：**只要读者可能照着执行/照做，就必须改**；纯历史记录（ADR、变更日志、`docs/archive`、
「原 `frontend/src/modules/...`，018 平移」这类显式历史说明）**保持原样**，不改写历史。

## 2. 改动清单（12 文件，纯引用/说明）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `.codebuddy/rules/module-boundary.md` | DETECT 命令 `frontend/src/modules/` → `{ExecutionView,CostView,MarketView}/module/`；「独立构建」示例路径 → `ExecutionView/standalone/` |
| 2 | `.codebuddy/rules/anti-patterns` 相关 `docs/spec/anti-patterns.md` | 3 条 `rg` 检测命令改指根级模块（`{...}/module/{components,views}`） |
| 3 | `.codebuddy/rules/coding-style.md` | 类型文件示例 `modules/execution/types/` → `ExecutionView/module/types/` |
| 4 | `.codebuddy/rules/project-context.md` | 模块 `services/` 示例路径 |
| 5 | `.codebuddy/skills/code-cleanup/references/ruleset-cl.md` | 独立构建入口路径 |
| 6 | `docs/spec/module-onboarding.md` | 目录树改为 `<NewModule>/{module,standalone}/`；A.3 注册 import 改用模块别名；A.5 测试命令路径 |
| 7 | `docs/spec/project-structure.md` | 「shell 内模块拆分」列表改为三个根级模块 |
| 8 | `docs/api-contracts.md` | 前端结构树：`frontend/src/` 只留壳层与共享层，模块列在根级 |
| 9 | `README.md` | 仓库结构树（前端子树重写 + 三模块根级条目）与「§6 前端入口唯一表」（含 `vite.base.ts` / `dist-modules/` 的过时描述） |
| 10 | `.github/knowledge/error-patterns.md` | 「模块入口不存在」排查指引里的入口路径 |
| 11 | `CostView/src/monitoring/anomaly_query.py` | docstring 指向 `CostView/module/lib/thresholds.ts` |
| 12 | `scripts/cleanup/detectors/frontend.py`、`frontend/vite.base.ts`、`.gitignore` | 注释/文档串同步（`.gitignore` 另补「勿改回非锚定 `data/`」的说明） |

## 3. 顺带核实（无需改动）

- **无空目录残留**：`git mv` 是整个目录重命名，`frontend/src/modules/` 已随之消失（实测 `frontend/src` 下无空目录）。
- **无静默未跟踪文件**：六个模块目录（3 × `module` / `standalone`）实测 **已跟踪数 == 磁盘文件数**（39/2、15/2、94/2），
  不存在 012 那类 `.gitignore` 误伤（`git status --ignored` 该范围内为空）。
- 历史引用（ADR-0014/0015/0018、README 变更日志、`docs/archive/`、`ExecutionView/README.md` 的「原 …」说明、
  `open-todos.md` T3 原文）**按原则保留**。

## 4. 验收

| 项 | 结果 |
|---|---|
| 残留复查 | `git grep 'src/modules/'` 等 patterns 仅剩历史说明与 `<module>` 占位符 |
| `audit_doc_drift.py` | 通过（22 ADRs / 3 modules） |
| `audit_cross_imports.py` | 无违规 |
| `pytest backend/api/tests/boundaries/` | 23 passed, 1 skipped |
| CI | 全门禁 pass |

## 5. 本次不做

- 不改写 ADR 与 `docs/archive/`（历史记录原则）。
- 不为 CostView/MarketView 新增 `package.json`（依赖由仓库根提升的 `node_modules` 提供；若要三模块形态完全对齐需纳入 workspaces 成员，属独立决策）。
- 不清偿 `react-hooks/set-state-in-effect` 存量债务（18 条，独立清理项）。
