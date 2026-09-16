# 018 — costview / marketview 根级平移（三模块形态一致）

> 特性：`018-costview-marketview-root-extract`
> 分支：`018-costview-marketview-root-extract`（worktree `../EMSXView-wt-018-costview-marketview-root-extract`）
> 定位：P1「模块形态一致性」第 1 项；上游 `specs/012`（ExecutionView 首迁）、`specs/013`（workspaces）、`specs/017`（拓扑同源收敛）

---

## 1. 目标形态

三个业务模块**全部**为仓库根级目录，与 `frontend/` 平级；`frontend/src/` 只保留壳层与共享层。

```
ExecutionView/{module,standalone}     ← 012 已完成
CostView/{module,standalone}          ← 本 PR（原 frontend/src/modules/costview + frontend/src/standalone/costview）
MarketView/{module,standalone}        ← 本 PR（原 .../marketview）
frontend/src/{app,shared,components,standalone/shell-less.tsx}   ← 壳层 + 共享层（`frontend/src/modules/` 已空）
```

## 2. 改动清单

### 2.1 目录平移（`git mv`，历史保留）
| 源 | 目标 |
|---|---|
| `frontend/src/modules/costview/` | `CostView/module/` |
| `frontend/src/standalone/costview/` | `CostView/standalone/` |
| `frontend/src/modules/marketview/` | `MarketView/module/` |
| `frontend/src/standalone/marketview/` | `MarketView/standalone/` |

### 2.2 接线
| # | 文件 | 改动 |
|---|---|---|
| 1 | `scripts/module_layout.py` | costview/marketview 的 `root` 改指向根级目录；新增 `standalone_root` 字段并纳入前端扫描根 |
| 2 | `frontend/vite.config.ts` | 别名指向根级目录；`test.include` 增两个模块；`manualChunks` chunk 匹配串改 `/CostView/module/`、`/MarketView/module/` |
| 3 | `frontend/vite.base.ts` | `MODULE_LAYOUTS` 的 costview/marketview 增 `root` 覆盖（入口 HTML 已在 `frontend/` 之外） |
| 4 | `frontend/tsconfig.app.json` | `paths` 指向根级目录；`include` 增 4 条（module + standalone） |
| 5 | `frontend/src/app/App.tsx` | 注册副作用 import 改用 `@costview` / `@marketview` 别名 |
| 6 | `CostView/module/module.registry.ts`、`MarketView/module/module.registry.ts` | `loader` 改用模块别名（与 `@execution/ExecutionModule` 同风格） |
| 7 | `CostView/standalone/main.tsx`、`MarketView/standalone/main.tsx` | `@costview/module.registry`、`@/index.css`、`@/standalone/shell-less` |
| 8 | `frontend/tailwind.config.js` | `content` 增 4 条 glob（**漏改会让模块独占 utility 被 purge，UI 静默丢样式**） |
| 9 | `frontend/package.json` | `lint:modules` 覆盖三个模块目录 |

### 2.3 顺带修复的「静默守卫失效」（本 PR 实测踩到）
| # | 文件 | 问题 | 处置 |
|---|---|---|---|
| 10 | `scripts/audit_doc_drift.py` | `get_module_registry_ids()` 硬编码 `frontend/src/modules/*/module.registry.ts` → 迁移后取到空集合，**CORE 检查「注册模块 ↔ 边界文档」静默通过**（输出从 "3 modules" 变 "0 modules"） | 改为按 `module_layout.FRONTEND_MODULES` 定位；并新增「登记非空却找不到任何 registry ⇒ 直接报 CORE 漂移」的显式兜底 |
| 11 | `backend/api/tests/boundaries/test_module_registry_consistency.py` | 同样的硬编码 → 迁移后测试 `skip("no module registries found")`，守卫静默关闭 | 改为按 `module_layout` 派生 |
| 12 | `scripts/module_layout.py` | standalone 入口根未纳入扫描根 → `frontend/src/standalone/shell-less.tsx` 失去消费者，被 OE-06 误报（实测 109→110） | 新增 `standalone_root` 并纳入 `FRONTEND_SCAN_ROOTS`（覆盖回到平移前水平） |

### 2.4 文档
| # | 文件 | 改动 |
|---|---|---|
| 13 | `.codebuddy/rules/{coding-style,project-context,module-boundary}.md` | 模块放置映射 / 模块清单 / DETECT 命令改指根级目录 |
| 14 | `docs/spec/{anti-patterns,project-structure}.md`、`docs/handoff-costview-html-report.md`、`README.md`、`MarketView/README.md`、`AGENTS.md`(→`CODEBUDDY.md`) | 路径引用同步 |
| 15 | `docs/open-todos.md` | T3 核实为**已完成**（`CostView/module/lib/monitoring-metrics.ts:47` 已是 `'成交股数'`）并标注证据 |
| 16 | `specs/018-costview-marketview-root-extract/plan.md` | 本文件 |

## 3. 验收（全部实测）

| 项 | 结果 |
|---|---|
| `npm ci`（仓库根） | 429 packages / exit 0 |
| `npm run typecheck` | exit 0（无输出） |
| `npm test` | **21 文件 / 169 用例全绿**（三个模块的用例均在各自新根目录下被收集） |
| `npm run build`（主应用） | exit 0，`frontend/dist/` = `assets` + `strategy-data` |
| `npm run build:costview` / `build:marketview` / `build:execution` | 三者全部 exit 0；`frontend/dist-modules/{costview,marketview,execution}/index.html` 与 `frontend/dist/` **并存** |
| Tailwind 扫描覆盖（purge 风险） | 主应用 CSS 命中 costview/marketview 独占类 `min-w-[1180px]`、`grid-cols-[1fr_auto_1fr]`，以及 ExecutionView 的 `min-w-[16px]` |
| `python scripts/audit_cross_imports.py` | 无违规 |
| `python scripts/audit_doc_drift.py` | 通过，**3 modules registered with boundary rules**（修复前静默为 0） |
| `pytest backend/api/tests/boundaries/` | **23 passed, 1 skipped**（多出的 skip 已消除；剩余 1 个为既有 AP-04 记录型 skip） |
| 全量 OE 扫描 | **339 文件 / 存量 109**，构成与平移前逐项一致（OE-01:1、OE-02:8、OE-05:80、OE-06:0、OE-07:20）—— 证明扫描覆盖无回归、无新增误报 |
| `npm run lint:modules` | 覆盖三个模块后报 **18 条**存量 `react-hooks/set-state-in-effect`（ExecutionView 14 + CostView/MarketView 4；均为既有债务，非本次引入，且不在 CI 门禁内） |

## 4. 风险与取舍

- **`frontend/src/modules/` 成为空目录**：git 不跟踪空目录，该目录在各机器上会残留（无害）；如需清理手动删除即可。
- **三个模块均未自带 `package.json`**（只有 `ExecutionView` 因是 workspaces 成员而有）：CostView/MarketView 的 TS 依赖由仓库根提升的 `node_modules` 提供（ADR-0020 之后裸包解析天然可用）。若要让三者形态完全对齐，需把它们也纳入 workspaces 成员——属独立决策，本次不做。
- **回退**：单一提交，`git revert` 即回到「模块在 `frontend/src/modules/`」形态。

## 5. 本次不做

- 不动 `frontend/src/components/ui/*`（共享 UI 套件）与 `@shared/*` 的归属。
- 不为 CostView/MarketView 新增 `package.json`（见风险节）。
- 不清偿 lint 存量债务（17 条 react-hooks），属独立清理项。
