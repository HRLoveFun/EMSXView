# 012 — ExecutionView 根级独立化（从 frontend/ 迁出）

> 特性：`012-executionview-root-extract`
> 分支：`012-executionview-root-extract`（worktree `../EMSXView-wt-012-executionview-root-extract`）
> 前置：[`011-executionview-module-contract`](../011-executionview-module-contract/plan.md)（模块契约化，已合并 PR #48）
> 目标形态：与 `CostView/`、`MarketView/` 平级的仓库根级目录，源码与独立构建入口均不再嵌套在 `frontend/` 内

---

## 1. 为什么

现状：ExecutionView 的前端实现位于 `frontend/src/modules/execution/`，被 `frontend/` 的目录树「吞掉」——无法像 `CostView/`、`MarketView/` 那样一眼看出它是一个独立业务模块，模块边界只能靠文档与别名约定维持。

目标：把实现与独立构建入口迁到仓库根 `ExecutionView/`，与既有业务模块同级；`frontend/` 退化为「Shell + 共享契约层 + 统一工具链」。

## 2. 目标目录布局

```
ExecutionView/                # 根级独立模块目录（与 frontend/、CostView/、MarketView/ 平级）
├── README.md                 # 职责边界 / 接口契约 / 运行与构建
├── module/                   # 原 frontend/src/modules/execution/**
│   ├── module.registry.ts    # 自注册描述符
│   ├── module.contract.ts    # 对外接口契约
│   ├── ExecutionModule.tsx
│   └── components/ hooks/ views/ services/ stores/ types/ lib/ data/
└── standalone/               # 原 frontend/src/standalone/execution/**
    ├── index.html
    └── main.tsx
```

别名：`@execution` → `ExecutionView/module`（`@shared` / `@app` / `@` 仍指向 `frontend/src`）。

## 3. 形态边界（本次不做）

- **不引入自有 `package.json` / `node_modules`**：模块源码仍由 `frontend/` 统一打包，工具链与依赖只有一份。若让 `ExecutionView/` 自带依赖，Vite 从 `ExecutionView/node_modules` 解析 `react` 会打包出**第二份 React**（Invalid hook call）；正解是 npm workspaces + `resolve.dedupe`，属独立一轮（需 ADR + lockfile/CI 工作流改造）。
- **不做独立部署**：仍是同一个前端产物、同一套 Nginx/静态托管与后端代理。
- **不动 costview / marketview**：两者保持 `frontend/src/modules/*`，迁出按同一 SOP 单独推进。

## 4. 改动清单

### 4.1 目录迁移
| # | 动作 |
|---|---|
| 1 | `git mv frontend/src/modules/execution ExecutionView/module` |
| 2 | `git mv frontend/src/standalone/execution ExecutionView/standalone` |

### 4.2 frontend 接线（跨 root 引用 & 跨 root 解析）
| # | 文件 | 改动 |
|---|---|---|
| 3 | `frontend/vite.config.ts` | `@execution` 别名指向 `../ExecutionView/module`；`server.fs.allow` 放行仓库根；测试 `include` 纳入 `../ExecutionView/**` |
| 4 | `frontend/vite.base.ts` | 新增 `MODULE_LAYOUTS`（`root?` / `entry` / `chunkMatch`）：execution 的 `root` 指向 `../ExecutionView/standalone`（否则 rollup 无法 emit 位于 root 之外的 HTML 入口）、`outDir` 改绝对并 `emptyOutDir: true`、`css.postcss` 显式指向 `postcss.config.js`（root 移出 frontend 后自动查找失效） |
| 5 | `frontend/tsconfig.app.json` | `paths."@execution/*"` → `./../ExecutionView/module/*`；`include` 增 `../ExecutionView/module`、`../ExecutionView/standalone` |
| 6 | `frontend/src/app/App.tsx` | 注册副作用 import 改为别名 `@execution/module.registry` |
| 7 | `ExecutionView/standalone/main.tsx` | 相对路径改为别名（`@/index.css`、`@execution/module.registry`） |
| 8 | `scripts/devtools/link-module-deps.mjs` + `frontend/package.json`(`postinstall`) | 自动建立「仓库根 `node_modules` → `frontend/node_modules`」链接。**原因**：Node/TS/Vite 解析裸包（`react` 等）从引用方目录逐级向上找 `node_modules`，根级模块否则解析失败；链接保证全仓库仍只有一份物理依赖（避免第二份 React） |
| 9 | `frontend/tailwind.config.js` | `content` 增 `../ExecutionView/module/**`、`../ExecutionView/standalone/**`。**原因**：类名扫描不到时 ExecutionView 独占的 utility 会被 purge，UI 静默失去样式 |
| 10 | `frontend/package.json`(`lint:modules`) | ESLint 的 base path 是 cwd，`eslint .` 无法覆盖 `frontend/` 之外的源码，故新增从仓库根以显式配置运行的 lint 脚本（覆盖 94 文件）。**修正（2026-09-16）**：原记录「0 error」有误——该脚本会报出 14 条 `react-hooks/*` 存量问题（与 `npm run lint` 在 `frontend/src` 报 6 条同源，均属既有债务、非 CI 门禁项），详见 `specs/013-frontend-workspaces/plan.md` §5 |

### 4.3 门禁与审计（防「路径变了、守卫失效」）
| # | 文件 | 改动 |
|---|---|---|
| 11 | `scripts/quality_gate/config.py` | `FRONTEND_SCAN_ROOT` → `FRONTEND_SCAN_ROOTS`（多根）+ `FRONTEND_ALIASES` 语义改为**仓库根相对** |
| 12 | `scripts/quality_gate/context.py` | `collect_frontend_files` 覆盖多根 |
| 13 | `scripts/quality_gate/detectors/frontend_light.py` | `_resolve_path` 按仓库根相对解析别名 |
| 14 | `scripts/cleanup/config.py`、`scripts/cleanup/detectors/frontend.py` | 同上（清理门禁与质量门禁共用别名表） |
| 15 | `scripts/audit_cross_imports.py` | `frontend_execution` 扫描根 → `ExecutionView/module` |
| 16 | `backend/api/tests/boundaries/test_cross_module_imports.py` | execution 侧 4 条 TS 规则的 `base_dir` → `ExecutionView/module` |

### 4.4 文档
| # | 文件 | 改动 |
|---|---|---|
| 17 | `ExecutionView/README.md` | 新增（对齐 CostView/MarketView README 风格） |
| 18 | `docs/spec/project-structure.md` | 结构树 / 模块拆分小节 |
| 19 | `docs/spec/module-boundary.md` | §1.1 / §1.3 / §1.7 的 DETECT 路径 |
| 20 | `docs/spec/anti-patterns.md`、`docs/api-contracts.md` | 路径引用 |
| 21 | `README.md`、`AGENTS.md`（hook 同步 `CODEBUDDY.md`） | 模块位置与映射维护点 |
| 22 | `.gitignore` | 注释中的旧路径说明 |
| 23 | `.codebuddy/rules/coding-style.md` | 文件放置映射新增 `ExecutionView/module`（该文件按 `.gitignore` 为本地文件，不进版本库） |

## 5. 验收矩阵

| 需求 | 检验方法 |
|---|---|
| 源码不在 frontend 内 | `ExecutionView/module` 存在且 `frontend/src/modules/execution` 不存在 |
| Shell 仍可统一构建 | `npx tsc -b`、`npx vitest run` 全绿；`npm run build` 通过 |
| 独立构建入口可用 | `npm run build:execution` 产出 `dist/execution/` |
| 边界契约不失效 | `python scripts/audit_cross_imports.py`；`pytest backend/api/tests/boundaries/` |
| 质量/清理门禁仍能索引模块 | `python scripts/quality_gate.py --ruleset oe` 无「解析失败导致的批量误报」（对比迁移前后 finding 数量与类别） |
| 文档无漂移 | `python scripts/audit_doc_drift.py` |

## 6. 风险与回退

- **风险 1：别名解析失效导致 OE 误报**。若 `@execution` 解析不到，模块内所有导出会被判「无消费者」，产生上百条 OE-06。缓解：迁移后跑全量 OE 扫描，逐类核对 finding 数量（应与迁移前同量级、仅路径变化）。
- **风险 2：OE 基线按路径重键**。基线库（`scripts/reports/quality_gate/quality_gate.db`，不入库、按 worktree 独立）中 execution 文件的指纹随路径变化，需在新路径下重建基线；这属「同量债务换路径」，不新增实际债务。
- **风险 3：裸包解析断裂**（实测已触发 TS2307 `Cannot find module 'react'`）。模块离开 `frontend/` 后，Node/TS/Vite 从引用方目录向上找不到 `node_modules`。缓解：`scripts/devtools/link-module-deps.mjs` 自动建立仓库根链接，共用同一份依赖。
- **风险 4：Tailwind purge 静默丢样式**（最隐蔽）。`content` 未覆盖根级模块时，ExecutionView 独占的 utility 会被 purge，UI 无样式但类型检查与测试全绿。缓解：补 `content` globs，并用「仅 ExecutionView 使用的类」（`min-w-[16px]`）在产物 CSS 中做存在性断言。
- **风险 5：standalone 构建的 root 语义**。入口 HTML 位于 vite root 之外时 rollup 直接报错；root 移出 `frontend/` 又会让 postcss 配置查找与 outDir 清空语义失效。缓解：`MODULE_LAYOUTS.root` + 显式 `css.postcss` + `emptyOutDir: true`，并实测 costview 产物路径与迁移前一致。
- **风险 6：ESLint 覆盖面缩水**。ESLint 的 base path 是 cwd，`eslint .` 无法覆盖 `frontend/` 之外的源码。缓解：新增 `lint:modules` 从仓库根以显式配置运行。
- **已知遗留**：`npm run build`（outDir `frontend/dist`）与 `npm run build:<module>` 先后执行时前者会清空后者产物——已由 [`specs/013-frontend-workspaces`](../013-frontend-workspaces/plan.md) 修复（模块产物改到 `frontend/dist-modules/<module>/`）。
- **回退**：整轮迁移为单一提交，`git revert` 即可回到 011 之后的形态。

## 7. 后续（不在本轮）

1. ~~**npm workspaces**~~：已由 [`specs/013-frontend-workspaces`](../013-frontend-workspaces/plan.md)（ADR-0020）落实——根 `package.json` 统一 lockfile 与依赖树，`ExecutionView/package.json` 自带依赖声明，`resolve.dedupe` 保证单实例 React。差异：`shared` **未**提升为独立根级包（仍在 `frontend/src/shared`）。
2. **costview / marketview 同构迁移**：按本轮 SOP 平移，保持三模块形态一致。**（尚未实施）**
3. **独立部署**：若确需单独发布，再评估 iframe / Module Federation 与认证、handoff 通道。**（尚未实施）**
