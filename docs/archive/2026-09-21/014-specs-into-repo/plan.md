# 014 — 必读规范文件入库（coding-style / project-context）

> 特性：`014-specs-into-repo`
> 分支：`014-specs-into-repo`（worktree `../EMSXView-wt-014-specs-into-repo`）
> 定位：P0「作业地基」第 1 项 —— 解掉「规范文件不在版本库 ⇒ 想改却改不了」的死结

---

## 1. 问题（实测证据）

`.gitignore` 只把 `.codebuddy/rules/` 下的两份额外白名单化：

```
.codebuddy/rules/*                        # 默认全部忽略
!.codebuddy/rules/module-boundary.md      # 白名单 1
!.codebuddy/rules/agent-workflow.md       # 白名单 2
```

但 `AGENTS.md` 的「文档阅读顺序（必读）」把另外两份列为第 2、3 项：

2. `.codebuddy/rules/project-context.md` — 技术栈与模块清单
3. `.codebuddy/rules/coding-style.md` — 命名/目录/状态管理

后果（本次会话直接踩到）：

1. **新克隆 / CI / 其他 Agent 看不到这两份「必读」文档**——`AGENTS.md` 的引用在远端仓库中指向不存在的文件。
2. **仓库结构演进后无人能同步它们**：PR #49（ExecutionView 迁出 frontend）、PR #53（npm workspaces + `dist-modules`）都无法更新这两份规范文件，因为它们在版本库里不存在。实测已确认漂移：
   - `coding-style.md` 功能→目录映射仍写 `frontend/src/modules/<module>/`，未含根级 `ExecutionView/module/`；也没有前端包管理（npm workspaces）条目。
   - `project-context.md` 仍写「四个懒加载 React 模块位于 `src/modules/`」（现只剩 2 个）、示例路径仍是 `modules/execution/services/execution-api.ts`（已迁）。

## 2. 决策

1. 把 `coding-style.md` 与 `project-context.md` **纳入版本库**（继续留在 `.codebuddy/rules/`，与已入库的两份规范同级），`.gitignore` 增加两条白名单并写明理由。
2. 同一提交内**修正上表已确认的漂移**，使入库版本与当前仓库结构一致（不然入的是过期规范）。

## 3. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `.gitignore` | 新增 `!.codebuddy/rules/coding-style.md`、`!.codebuddy/rules/project-context.md` + 理由注释 |
| 2 | `.codebuddy/rules/coding-style.md` | 功能→目录映射：前端模块代码补 `ExecutionView/module/`（根级独立模块 + 自带依赖声明）；新增「前端包管理」行（workspaces 根锁 + 仓库根安装） |
| 3 | `.codebuddy/rules/project-context.md` | 数据获取示例路径改为 `ExecutionView/module/services/execution-api.ts`；模块架构改为「costview/marketview 在 `frontend/src/modules/`，ExecutionView 在根级」+ 包管理与产物目录（`dist` / `dist-modules`）两条 |
| 4 | `specs/014-specs-into-repo/plan.md` | 本文件 |

## 4. 验收

| 需求 | 检验方法 |
|---|---|
| 两份文件进入版本库 | `git ls-files .codebuddy/rules/` 含 4 份；`git check-ignore` 对两份返回空 |
| 新克隆即可读到 | fresh worktree 中 `Test-Path .codebuddy/rules/{coding-style,project-context}.md` 为真 |
| 文档漂移门禁仍通过 | `python scripts/audit_doc_drift.py` |
| 内容与结构一致 | 两份文件中不再出现 `modules/execution`；出现 `ExecutionView/module` 与 workspaces 说明 |

## 5. 风险

- **主工作树 `git pull` 时的本地副本**：这两份文件在既有各机器上是「未跟踪但被忽略」的本地文件。合并后它们变为跟踪文件，本地旧副本会被检出覆盖（git 对 *ignored* 的未跟踪文件不报 “would be overwritten”，直接覆盖）。若某机器上的本地副本有**未提交的私有改动**，会被覆盖 —— 处置：合并后如 `git pull` 报错，先备份/移走本地副本再 pull。
- **双份规范源**：`AGENTS.md` 内的「关键约定」与 `coding-style.md` 有重叠内容，仍存在两处维护的可能；本次不做合并（属另一议题），仅在 `.gitignore` 注释中标注入库理由。
