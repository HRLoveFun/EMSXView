# 工具矩阵与降级策略

本 skill 的**能力下限由内置检测器保证**（纯标准库 `ast`，零第三方依赖，永远可用）。
外部工具是**可选增强**：能补足跨语言引用分析、运行时画像与打包分析的能力，但缺失时不阻塞流程。

---

## 一、静态分析（死代码 / 未使用导出）

| 生态 | 工具 | 能力 | 安装 | 与本 skill 的关系 |
|---|---|---|---|---|
| JS/TS | **knip** | 一次分析 5 类：未使用文件、未使用导出、未使用依赖、未解析 import、未使用 devDependencies | `npx knip --reporter json`（免安装） | 最强补充。**必须与 CL-10/OE-06 交叉核对**：knip 会把入口配置读错而漏报/误报 |
| JS/TS | ts-prune | 仅未使用导出 | `npx ts-prune` | knip 的降级替代 |
| Python | **vulture** | 未使用函数/类/变量/属性/import，可配 `--min-confidence` | `pip install vulture` → `vulture . --min-confidence 80` | 覆盖 CL-02 的类方法与局部符号（本 skill 刻意不判类方法，交给它） |
| Python | ruff（F401/F811/F841/ARG） | 未使用 import/变量/参数 | `pip install ruff` → `ruff check --select F,ARG` | 与 CL-06 重叠；ruff 更准，优先采信 ruff |
| Python | pyright / mypy | 类型层面不可达与未使用 | `pyright backend/ CostView/src/ data_access/ platform_data/`（见 AP-10） | 类型收窄能暴露「永不成立的分支」 |
| 依赖 | deptry / `pip-audit` | 未使用/缺失/漏洞依赖 | `pip install deptry` → `deptry .` | 补足「无用依赖」清理（knip 覆盖 JS 侧） |
| 多语言 | tree-sitter 系 DCE 工具 | 跨语言常量折叠 / 特性开关清理 | 视工具而定 | 仅在需要清理 feature flag 时引入 |

**降级策略**：knip/vulture 不可用时，用 `CL-02` + `CL-10` + `quality_gate --ruleset oe` 取并集，
并在报告中注明「外部工具未执行」——**不得静默跳过**。

---

## 二、复杂度与可维护性度量

| 工具 | 能力 | 命令 | 对应 |
|---|---|---|---|
| **radon** | 圈复杂度（CC）、维护性指数（MI）、原始度量（SLOC/注释率） | `radon cc -s -a <path>` / `radon mi -s <path>` | 与 `OE-05` / `PF-06` 互补 |
| **xenon** | 复杂度门禁（CI 用，超阈值即退出码非 0） | `xenon --max-absolute B --max-modules A --max-average A <path>` | 可用于把 OE-05 升级为 CI 硬门禁 |
| **gocyclo / lizard** | 多语言复杂度 | 视生态 | 非本栈 |

**阈值参考**（与 `scripts/quality_gate/config.py` 对齐，避免两套标准）：
CC > 15 报警（>30 严重）、嵌套 > 4、参数 > 7、函数 > 120 行。

---

## 三、运行时画像（性能优化的证据来源）

### 3.1 后端（Python）

| 目标 | 工具 | 命令 |
|---|---|---|
| CPU 火焰图（含 C 扩展） | **py-spy** | `py-spy record -o profile.svg -- python -m uvicorn ...`；常驻进程用 `py-spy top --pid <PID>` |
| 函数级耗时 | cProfile + pstats / snakeviz | `python -m cProfile -s cumtime -o prof.out <script>` → `python -m pstats prof.out` |
| 内存峰值/泄漏 | **tracemalloc** | 代码内 `tracemalloc.start()` + `take_snapshot()` 对比 |
| 逐行内存 | memory_profiler | `python -m memory_profiler <script>` |
| 分配火焰图 | memray / scalene | `python -m memray run --live <script>` |
| 回归基准 | pytest-benchmark | `pytest --benchmark-only --benchmark-compare` |

### 3.2 数据库（SQLite / 分析查询）

```sql
EXPLAIN QUERY PLAN SELECT ... ;   -- 确认是否走索引、是否出现 SCAN TABLE
```

- 关注 `SCAN`（全表扫描）与临时 B-tree（`USE TEMP B-TREE FOR ORDER BY`）；
- 大表聚合优先读预计算表（项目约定：TCA 指标读 `tca_route_summary`，禁止查询时实时聚合）；
- 索引/`LIMIT` 变更后必须复跑同一条 `EXPLAIN QUERY PLAN` 对比。

### 3.3 前端（React / Vite）

| 目标 | 工具 | 命令 |
|---|---|---|
| 重渲染分析 | React DevTools Profiler | 浏览器插件，「Highlight updates」+ 火焰图 |
| 打包体积 | `rollup-plugin-visualizer` / `vite-bundle-visualizer` | `npx vite-bundle-visualizer` |
| 首屏加载 | Lighthouse | 浏览器 DevTools → Lighthouse |
| 组件基准 | Vitest + `@testing-library/react` | 渲染次数断言（`render` 计数 spy） |

**本项目现状**：`vite.config.ts` 已按 `manualChunks` 切分 vendor（react / radix / icons / charts / ui），
体积问题的第一嫌疑通常是**未按需引入**（整库 import、未懒加载的模块 chunk）。

### 3.4 无 React DevTools 插件时的替代路径

DevTools Profiler 不可用（无插件 / 无法录制）时，按下列顺序降级 —— **不要因为拿不到火焰图就跳过后端与前端的实测**：

| 方案 | 能力 | 代价 | 局限 |
|---|---|---|---|
| **A. Vitest + `<React.Profiler>`** | commit 次数、`actualDuration`（组件级分解）；可做 A/B 对比（内联 props vs `useMemo`）；**可回归、可进 CI** | 零浏览器、零插件 | jsdom 无 layout/paint，测的是 React 渲染时间而非浏览器总耗时 |
| **B. `why-did-you-render`** | 控制台逐条输出「为何重渲染」（引用变化、props 相等但身份不同） | 仅 dev 依赖 + 一行 init | 仍需打开页面；输出为文本，无火焰图 |
| **C. 无头浏览器 + `MutationObserver` / `PerformanceObserver`** | 真实浏览器下的 **DOM 变更量**（重渲染的代理指标）与 **长任务（Long Task API）**；真实 layout/paint | 需 Playwright/agent-browser 等驱动 | 无法直接给出 React 组件级归属 |
| **D. `npx vite-bundle-visualizer`** | 打包体积归因（treemap/JSON） | 零交互 | 只覆盖体积，不覆盖运行时渲染 |

**判定标准（三条问题各自对应的最低要求）**：

- `PF-07` 下标 key → 看**列表重排时是否整段重建**：A 的 commit 次数或 C 的 DOM 变更量即可判定；
- `PF-07` 内联 props 破坏 memo →  **A 的 A/B 对比最直接**（同一组件，`useMemo` 前后 commit 次数对比）；
- `PF-08` Context value 未 memo → A 统计消费者组件在父组件重渲染时的 commit 次数即可；
- 「首屏/交互是否真的慢」→ 只有 **C**（真实浏览器 + Long Task）能回答；**D** 负责体积维度。

**推荐组合**：**A（主）+ D（补充）**，需要真实浏览器指标时再加 C。
A 的测试文件置于模块 `__tests__/`（`.codebuddy/rules/coding-style.md` 文件放置规范），
并断言「commit 次数不超过 N」以便回归拦截。

---

## 四、自动化守门（可选集成）

| 层次 | 手段 | 命令 |
|---|---|---|
| 提交前 | 清理增量快检（fail-open，25s 预算） | `git diff --cached --name-only \| grep -E '\.(py\|ts\|tsx)$' \| python scripts/cleanup.py --staged --quiet` |
| 提交前 | 既有质量门禁 | `.githooks/pre-commit` 已调用 `python scripts/quality_gate.py --staged` |
| CI | 清理门禁（新增项阻断） | `python scripts/cleanup.py --strict --report` |
| CI | 复杂度门禁 | `xenon --max-absolute C <paths>` |
| 周期任务 | 全量趋势追踪 | 每日/每周 `python scripts/cleanup.py --report`，跟踪存量清偿率 |

**注意**：`cleanup` 默认**不阻断**（清理决策需人工确认）；只有团队明确愿意接受误报时，
才把 CI 切到 `--strict`。切之前必须先跑一轮全量扫描并 `--suppress` 收口历史误报。

---

## 五、工具结果的使用纪律

1. **交叉核对**：外部工具与内置规则的结果必须**求并集后再人工分级**，不得只信一方
   （两者都会既漏报又误报，且误报集合不同）。
2. **不虚构结果**：工具未安装或执行失败时在报告注明「未执行」，**禁止**凭印象描述工具输出。
3. **不重复建框架**：能用现成工具解决的（如 ruff 的 F841）不要自己写检测器；
   本 skill 的内置检测器只覆盖项目特有语境（模块边界、预计算表约定、多入口前端图）。
4. **有变更先看基线**：任何工具引入后先建基线，再谈阻断（对应 `quality_gate` 的 guard 门禁演进）。
