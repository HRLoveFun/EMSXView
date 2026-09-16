# 013 — 前端依赖树收敛（npm workspaces）与模块产物目录隔离

> 特性：`013-frontend-workspaces`
> 分支：`013-frontend-workspaces`（worktree `../EMSXView-wt-013-frontend-workspaces`）
> 前置：[`012-executionview-root-extract`](../012-executionview-root-extract/plan.md)（ExecutionView 迁至仓库根，已合并 PR #49）
> 决策记录：[ADR-0020](../../docs/spec/adr/0020-frontend-npm-workspaces.md)

---

## 1. 为什么

012 把 ExecutionView 迁到仓库根后，留下两个未收口的问题（012 plan §7 已登记）：

1. **依赖解析靠自维护的隐式机制**：Node/TS/Vite 从引用方目录向上找 `node_modules`，根级模块因此解析不到裸包；过渡方案是 `frontend` 的 `postinstall` 建「仓库根 → `frontend/node_modules`」链接。
2. **ExecutionView 没有依赖声明**：其可用依赖完全由 `frontend/package.json` 隐式决定，与 CostView（`pyproject.toml`）、MarketView（`requirements.txt`）「自带依赖声明」的形态不一致。

另有一项迁移前既有的构建缺陷：`npm run build`（outDir `frontend/dist`）会清空 `dist/`，把 `npm run build:<module>` 写在 `dist/<module>` 的产物一并删掉。

## 2. 目标形态

```
<repo-root>/
├── package.json                     # workspaces 根（frontend + ExecutionView），统一 lockfile
├── package-lock.json                # 唯一 lockfile（原 frontend/package-lock.json 迁入）
├── ExecutionView/
│   ├── package.json                 # ★ 自带依赖声明（react/react-dom/lucide-react + 测试期依赖）
│   ├── module/  standalone/
├── frontend/
│   ├── package.json                 # workspace 成员（保留脚本，移除过渡用 postinstall）
│   ├── dist/                        # 主应用产物（不变）
│   └── dist-modules/<module>/       # ★ 独立模块产物（与 dist/ 分离，互不删除）
└── node_modules/                    # 提升后的依赖（npm workspaces 自动）
```

## 3. 改动清单

### 3.1 依赖拓扑
| # | 文件 | 改动 |
|---|---|---|
| 1 | `package.json`（新增，根） | `private` + `workspaces: ["frontend","ExecutionView"]` + 委派脚本（dev/build/typecheck/test/lint） |
| 2 | `ExecutionView/package.json`（新增） | 声明直接依赖与测试期依赖（版本区间与 frontend 对齐） |
| 3 | `frontend/package-lock.json` | 删除（由根 lockfile 取代） |
| 4 | `frontend/package.json` | 移除 `postinstall`（链接脚本）；新增 `typecheck` 脚本 |
| 5 | `scripts/devtools/link-module-deps.mjs` | 删除（过渡机制，workspaces 下不再需要） |
| 6 | `frontend/vite.config.ts` / `vite.base.ts` | 新增 `resolve.dedupe: ['react','react-dom']` |

### 3.2 产物目录隔离
| # | 文件 | 改动 |
|---|---|---|
| 7 | `frontend/vite.base.ts` | 模块 outDir 默认 `frontend/dist-modules/<module>`（原 `frontend/dist/<module>`） |
| 8 | `.gitignore` | 新增 `dist-modules/` |
| 9 | `frontend/src/standalone/{costview,marketview}/main.tsx`、`ExecutionView/standalone/main.tsx` | 注释中的输出路径 |

### 3.3 外围同步（安装入口变更的连带面）
| # | 文件 | 改动 |
|---|---|---|
| 10 | `.github/workflows/boundary.yml` | `cd frontend && npm ci` → 根 `npm ci`；`npx tsc -b --noEmit` / `npx vitest run` → `npm run typecheck` / `npm run test` |
| 11 | `.githooks/common.sh` | `DEPENDENCY_FILES`：`frontend/package-lock.json` → `package-lock.json` |
| 12 | `.githooks/post-checkout`、`scripts/devtools/wt-new.ps1` | worktree 就绪提示的安装指令改为仓库根 |
| 13 | `scripts/deploy/start-frontend.ps1` | 清理 vite 缓存的路径（提升后位于根 `node_modules/.vite`），两处都清 |
| 14 | `scripts/deploy/launch-emsxview.ps1` | 启动失败诊断文案中的安装指令 |
| 15 | `docs/spec/git-workflow.md` §6.3、`README.md`、`docs/ops/service-management.md`、`QUICKSTART.md`、`ExecutionView/README.md` | 安装指令与产物路径 |

### 3.4 文档
| # | 文件 | 改动 |
|---|---|---|
| 16 | `docs/spec/adr/0020-frontend-npm-workspaces.md`（新增） | 决策记录 |
| 17 | `docs/spec/memory.md`、`docs/spec/adr/README.md` | ADR 索引 |
| 18 | `specs/012-executionview-root-extract/plan.md` | §7「后续」第 1、3 项标注由 013 落实 |

## 4. 验收矩阵

| 需求 | 检验方法 |
|---|---|
| 依赖解析不再依赖链接脚本 | 删除链接脚本后，干净装机（根 `npm ci`）下 `npm run typecheck` 通过 |
| 只保留一份 React | 根 `node_modules/react` 唯一；`find node_modules -name react -maxdepth 4` 无嵌套副本；`resolve.dedupe` 已配置 |
| ExecutionView 自带声明 | `ExecutionView/package.json` 存在且覆盖其直接 import 的第三方包 |
| 安装入口变更已贯通 | grep 全仓库无「`cd frontend` + `npm install/ci`」残留；CI 用根安装 |
| 构建产物互不删除 | 依次 `npm run build` → `build:execution` → `build:costview`，三者产物同时存在 |
| 不破坏现有功能 | `npm run test`（21 文件 / 169 用例）、`python scripts/audit_cross_imports.py`、`pytest backend/api/tests/boundaries/`、`python scripts/audit_doc_drift.py` |

## 5. 风险与回退

- **风险 1：CI 装机方式变更**。`npm ci` 必须在仓库根且需要根 lockfile；漏改 CI 会直接失败（可观测，非静默）。
- **风险 2：`npx` 在子目录找不到 bin**。依赖提升后 `frontend/node_modules/.bin` 可能为空，故 CI 改走根 `npm run <script>`（npm 会把 workspace 及其上层的 `.bin` 加入 PATH）。
- **风险 3：部署脚本预检/缓存清理路径失效**。`start-frontend.ps1` 清 `frontend/node_modules/.vite`，提升后缓存位于根——改为两处都清（幂等，`-ErrorAction SilentlyContinue`）。
- **回退**：整轮为单一提交，`git revert` 回到「链接脚本 + 各自 lockfile」形态。
- **存量事实（非本次引入）**：`npm run lint`（frontend）与 `npm run lint:modules`（根级模块）目前均为**红**，分别报 6 / 14 条 `react-hooks/set-state-in-effect`、`react-hooks/purity` 存量问题；ESLint 不在 CI 门禁内。本次仅把 `dist-modules` 加入 `globalIgnores`，不修这些存量问题（属独立清理项）；同时修正 `specs/012` 中「lint:modules 0 error」的错误记录。

## 6. 本次不做

- **不把 ExecutionView 做成可脱离 frontend 独立构建**：它仍消费 `frontend/src/components/ui/*` 与 `@shared/*` 契约层；「自带依赖声明」只解决声明与解析归属。
- **不迁移 costview / marketview**：两者仍在 `frontend/src/modules/*`，按 012 的 SOP 单独平移。
- **不引入 pnpm / turbo 等其它包管理器**：workspaces 已满足需求，避免额外工具链。
