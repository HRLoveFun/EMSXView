# ADR-0020: 前端依赖树收敛为 npm workspaces（frontend + ExecutionView）

> 状态: Accepted
> 日期: 2026-09-16
> 标签: frontend, build, tooling, process

## 背景 (Context)

ADR-0019 之后，ExecutionView 已独立为仓库根级目录 `ExecutionView/`（见 `docs/archive/2026-09-21/012-executionview-root-extract/plan.md`）。
这带来两个与依赖解析相关的问题：

1. **裸包解析断裂**：Node / TypeScript / Vite 解析裸包说明符（`react`、`lucide-react` …）时是从**引用方文件所在目录逐级向上**查找 `node_modules`。源码离开 `frontend/` 后，仓库根没有 `node_modules`，`ExecutionView/**` 下所有裸包导入都会解析失败（实测 `TS2307: Cannot find module 'react'`）。
2. **依赖声明缺位**：`ExecutionView/` 没有任何依赖声明，其可用的包完全由 `frontend/package.json` 隐式决定——与 `CostView/`（`pyproject.toml`）、`MarketView/`（`requirements.txt`）「自带依赖声明」的形态不一致。

过渡方案（PR #49）是 `frontend` 的 `postinstall` 自动建立「仓库根 `node_modules` → `frontend/node_modules`」链接。该方案可用，但引入了**需自行维护的隐式机制**：链接是每份工作树的本地产物，缺失时报错信息与根因相距很远；且依赖声明的单一来源问题仍未解决。

## 决策 (Decision)

1. 仓库根引入 **npm workspaces**，成员为 `frontend` 与 `ExecutionView`：

   ```json
   { "private": true, "workspaces": ["frontend", "ExecutionView"] }
   ```

2. **lockfile 与依赖树统一到仓库根**：`frontend/package-lock.json` 移除，改为根 `package-lock.json`；安装入口统一为「仓库根 `npm install` / `npm ci`」（workspaces 会按需提升，仓库根只保留一份物理依赖）。
3. **ExecutionView 自带依赖声明**：`ExecutionView/package.json` 声明其直接引用的运行时依赖（`react` / `react-dom` / `lucide-react`）与测试期依赖（`vitest` / `@testing-library/*`），版本区间与 `frontend` 对齐以保证提升为同一份实例。
4. 两个 vite 配置均加 `resolve.dedupe: ['react', 'react-dom']`，作为「只取一份 React」的显式护栏（防止版本区间未来的漂移导致双实例）。
5. 删除过渡机制 `scripts/devtools/link-module-deps.mjs` 与 `frontend` 的 `postinstall`。
6. 模块构建产物与主应用产物**分目录隔离**：主应用 `frontend/dist/`，独立模块 `frontend/dist-modules/<module>/`——消除「主应用构建清空 `dist/` 时连带删除模块产物」的既有缺陷。

## 后果 (Consequences)

### 正面

- 根级模块的裸包解析由 npm 提升**天然**成立，不再依赖自维护的链接脚本。
- 依赖声明回归各模块自身，依赖树只有一份 lockfile（可审计、可复现）。
- `resolve.dedupe` 把「只能有一份 React」从约定升级为构建期约束。
- 主应用构建与模块构建产物互不覆盖。

### 负面 / 取舍

- **安装入口变了**：从 `cd frontend && npm install` 改为仓库根 `npm install`。所有文档、`.githooks`、worktree 就绪提示、部署脚本必须同步，否则报错信息会很隐蔽。
- lockfile 位置变更导致一次性大 diff（`frontend/package-lock.json` → 根 `package-lock.json`）。
- 依赖版本区间在 `frontend` 与 `ExecutionView` 各出现一次，存在漂移风险；由 `resolve.dedupe` + 版本对齐惯例缓解，但无机器强制。
- `ExecutionView` 仍依赖 `frontend/src/components/ui/*`（shadcn UI 套件）与其工具链，**尚未**做到可脱离 `frontend` 独立构建——本 ADR 只解决「依赖声明与解析」，不改变打包归属。

### 对其他 ADR 的影响

- 被引用: ADR-0008（前端模块自注册模式）——本决策不改模块发现机制，只改依赖拓扑。
- 关联: `docs/archive/2026-09-21/012-executionview-root-extract/plan.md`（本 ADR 落实其 §7「后续」第 1 项）。

## 备选方案 (Considered Alternatives)

- **方案 A：保留根 `node_modules` 链接脚本（PR #49 过渡实现）**
  - 否决原因：隐式机制需长期维护；每份工作树都要重新生成；依赖声明单一来源问题未解决。
- **方案 B：仅靠 `resolve.dedupe` + 各配置的 `resolve.alias` 手工映射到 `frontend/node_modules`**
  - 否决原因：TypeScript 与 Vite 的裸包解析并不走 alias；需为每个依赖手工登记，无法维护。
- **方案 C：`ExecutionView` 自带独立 `node_modules`（脱离 workspaces 自行安装）**
  - 否决原因：会打包出第二份 React（Invalid hook call）；且与「同一应用内嵌」的现实冲突。
- **方案 D：模块产物继续放 `frontend/dist/<module>`，改为关闭主应用构建的清空行为**
  - 否决原因：`dist/` 会残留历次哈希产物，污染部署目录；不如分目录干净。

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件：根 `package.json`、`ExecutionView/package.json`、`frontend/package.json`、`frontend/vite.config.ts`、`frontend/vite.base.ts`、`.github/workflows/boundary.yml`、`.githooks/common.sh`、`.githooks/post-checkout`、`scripts/devtools/wt-new.ps1`、`scripts/deploy/start-frontend.ps1`、`scripts/deploy/launch-emsxview.ps1`、`docs/spec/git-workflow.md` §6.3、`README.md`、`docs/ops/service-management.md`、`ExecutionView/README.md`。
- 配套验证：仓库根 `npm ci` 干净装机 → `npm run typecheck` / `npm run test` → `npm run build`、`npm run build:execution`、`npm run build:costview` 三者产物并存 → `npm run lint:modules`。
- 回滚策略：整轮为单一提交，`git revert` 即可回到「链接脚本」形态。
