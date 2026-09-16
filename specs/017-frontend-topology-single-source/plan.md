# 017 — 前端模块拓扑同源收敛（扫描根 / 路径别名）

> 特性：`017-frontend-topology-single-source`
> 分支：`017-frontend-topology-single-source`（worktree `../EMSXView-wt-017-frontend-topology-single-source`）
> 定位：P1「门禁可维护性」第 1 项，且是 [`018-costview-marketview-root-extract`](../018-costview-marketview-root-extract/plan.md) 的前置
> 上游：`specs/012-executionview-root-extract`（首次暴露该问题）、`specs/013-frontend-workspaces`

---

## 1. 问题（实测证据）

「某个模块的源码在哪个目录」这一事实，此前散落在 **4 处**：

| # | 位置 | 形式 |
|---|---|---|
| 1 | `scripts/quality_gate/config.py` | `FRONTEND_SCAN_ROOTS` + `FRONTEND_ALIASES`（含 `ExecutionView/module`） |
| 2 | `scripts/cleanup/config.py` | 同名 `FRONTEND_SCAN_ROOTS`，字面复制 |
| 3 | `scripts/audit_cross_imports.py` | `MODULE_SCAN_ROOTS`，硬编码 `REPO_ROOT / "ExecutionView" / "module"` 等 |
| 4 | `backend/api/tests/boundaries/test_cross_module_imports.py` | 硬编码扫描根 |

**漏改的后果是静默的**（这是本次立项的真正理由，不是「重复代码不好看」）：

- 模块在 import 图里不可达 ⇒ OE-01「死模块」、CL-10「前端不可达文件」批量误报；
- 边界规则匹配不到任何文件 ⇒ 守卫形同关闭，而 **CI 依然全绿**。

012 迁 ExecutionView 时已一次性改了 4 处（当时的实际工作量），018 平移 costview/marketview 会再来一遍。

同时发现一处**死配置**：`scripts/cleanup/config.py` 的 `FRONTEND_SCAN_ROOTS` 全仓库无任何引用
（清理门禁的前端文件收集实际复用 `scripts.quality_gate.context.collect_frontend_files`）。

## 2. 决策

新增 `scripts/module_layout.py` 作为**唯一真相源**（纯数据 + 纯函数：不做文件系统探测、不解析构建配置），
其余位置全部派生：

```
scripts/module_layout.py            ← 唯一真相源
├── MODULE_LAYOUTS                  模块 id / 源码根 / 语言 / 别名 / optional
├── FRONTEND_ALIASES    ──→ scripts/quality_gate/config.py（再导出，检测器与清理门禁按原名读取）
├── FRONTEND_SCAN_ROOTS ──→ scripts/quality_gate/config.py（再导出）、cleanup（删死配置）
├── MODULE_ROOTS/MODULE_GLOBS ──→ scripts/audit_cross_imports.py（派生扫描根）
└── MODULE_ROOTS        ──→ backend/api/tests/boundaries/test_cross_module_imports.py
```

并新增**漂移守卫** `backend/api/tests/boundaries/test_frontend_module_layout.py`（规则 ID `TOPO-DRIFT`，CI 内执行）：
比对 `module_layout` 与 `frontend/vite.config.ts`、`frontend/vite.base.ts`、`frontend/tsconfig.app.json`
的真实别名表，校验模块源码根 / 前端扫描根存在，并断言「声明了 `forbidden_imports` 的模块必须有扫描根」。

> 收敛之后，018 只需在 `MODULE_LAYOUTS` 改 3 行。

## 3. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `scripts/module_layout.py` | **新增**：模块拓扑唯一真相源（数据 + 派生视图 + `minimal_roots`） |
| 2 | `scripts/quality_gate/config.py` | 删除本地扫描根/别名表，改为从 `module_layout` 再导出（`config.FRONTEND_*` 对外不变） |
| 3 | `scripts/cleanup/config.py` | 删除**未被使用**的 `FRONTEND_SCAN_ROOTS`，改为指向唯一真相源的说明 |
| 4 | `scripts/audit_cross_imports.py` | `MODULE_SCAN_ROOTS` 改由 `MODULE_ROOTS` + `MODULE_GLOBS` 派生；新增 `modules_requiring_scan()` helper |
| 5 | `backend/api/tests/boundaries/test_cross_module_imports.py` | TS 规则扫描根改由 `MODULE_ROOTS` 派生（不再硬编码） |
| 6 | `backend/api/tests/boundaries/test_frontend_module_layout.py` | **新增**：拓扑漂移守卫（`TOPO-DRIFT`，6 个用例） |
| 7 | `docs/spec/module-onboarding.md` | 新增模块清单补「同步 module_layout + 构建配置」步骤 |
| 8 | `specs/012-executionview-root-extract/plan.md` | 标注该问题已由 017 收敛 |
| 9 | `specs/017-frontend-topology-single-source/plan.md` | 本文件 |

## 4. 验收

| 需求 | 检验方法 | 结果 |
|---|---|---|
| 行为零变化 | 全量 OE 扫描的扫描范围与结论与改造前一致 | 338 文件 / OE 新增 0 / 存量 109（文件数 +2 来自 016 与本 PR 新增的测试文件） |
| 四道守卫全绿 | `pytest backend/api/tests/boundaries/` | 23 passed, 1 skipped（较改造前 17+1 增加 6 条守卫用例） |
| 审计仍生效 | `python scripts/audit_cross_imports.py` | 无违规 |
| 门禁自测 | `python -m pytest scripts/quality_gate/tests/ -q` | 33 passed |
| **守卫真能拦漂移**（变异检查） | 内存里给 `FRONTEND_ALIASES` 加一个不存在的别名后跑守卫 | **3 failed**（vite.config.ts / vite.base.ts / tsconfig.app.json 三处别名比对同时失败） |

## 5. 风险

- **导入路径依赖**：`scripts/module_layout.py` 被 `scripts.quality_gate.*` 引用，要求仓库根在 `sys.path`
  （既有平铺入口 `scripts/quality_gate.py`、`scripts/cleanup.py` 已各自插入仓库根；测试侧显式插入）。
  回退：单一提交，`git revert` 即恢复四处各自维护的形态。
- **不改变任何扫描范围**：`FRONTEND_SCAN_ROOTS` 派生结果与改造前逐字相同（`["frontend/src", "ExecutionView/module"]`），
  已用全量扫描比对确认。

## 6. 本次不做

- 不把 `frontend/tsconfig.node.json` 等其余 tsconfig 纳入别名比对（仅 `tsconfig.app.json` 定义前端 paths）。
- 不做 `MODULE_LAYOUTS` 的自动发现（扫描文件系统推断模块）——显式登记 + 守卫比对更可审计。
