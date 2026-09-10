# ADR-0017: 代码清理与性能热点机制 — 复用 quality_gate 基础设施 + 独立基线

> 状态: Accepted
> 日期: 2026-09-10
> 标签: refactoring, cleanup, performance, tooling, scripts

## 背景 (Context)

仓库已有两套代码质量机制，但**清理与性能**这两类问题缺少可执行入口：

| 已有机制 | 覆盖 | 缺口 |
|---|---|---|
| `docs/spec/anti-patterns.md`（AP-01~AP-16） | 契约违规的**文档清单** | 无检测器，靠人工 `rg`，每轮全库清理都要重来 |
| `scripts/quality_gate/`（AP 适配 + OE-01~OE-07） | 冗余模块、过度抽象、重复代码块、复杂度、前端未使用导出 | 未覆盖：临时遗留文件、空壳模块、不可达代码、恒定条件、空存根、未使用局部变量、注释代码块、前端**文件级**可达性；也未覆盖任何**性能**维度 |

ADR-0014（2026-08-26）已用「一次性人工扫描 + 分批删除」清理了 73 文件 / 约 15,000 行，
但该过程**不可复用**：扫描脚本临时编写、判定标准散落在当次对话里、误报豁免靠记忆。
同类问题必然复发（每轮功能迭代都会留下新的死代码）。

同时，性能类问题（循环内 IO、全量加载、无界容器、前端渲染热点）在项目中**完全无静态线索**，
每次只能靠用户反馈"某接口慢"再人肉排查。

调研结论（GitHub 高星项目与主流工具实践）指向同一套工作方式：

1. **工具先行 + 人工确认**：knip / vulture / ts-prune 类工具只产出候选，社区共识是
   「静态分析不能证明代码已死」（反射、注册表、框架钩子、跨仓库消费者都是盲区）；
2. **基线演进而非一次性清零**：新增阻断、存量放行，否则存量规模会让门禁失去意义；
3. **先测量后优化**：性能优化必须由 profiler / `EXPLAIN` 提供证据，静态规则只用于**排序**；
4. **复查机制本身不能成为过度工程**：零依赖、共享基础设施、单文件精简。

## 决策 (Decision)

### 1. 新建 `scripts/cleanup/` 包，**复用** quality_gate 基础设施

直接导入 `quality_gate` 的 `Finding` / `RuleSet` / `Severity`（`models.py`）、
`ScanContext` 与文件收集（`context.py`）、AST 工具与指纹（`ast_utils.py`）、
`GateStore` 基线机制（`store.py`）、`scoring`（`scoring.py`）。

- **不**定义平行数据模型，**不**另写复杂度/AST 工具，**不**新建第二套门禁框架；
- CL-01（冗余文件）**包装** `quality_gate.detectors.dead_modules` 的 import 图算法，
  只扩大扫描范围（补入 `data_access/`、`scripts/`）并重标规则编号；
- 与 OE-xx 已覆盖的规则（OE-01/02/04/05/06/07）**不重复实现**，任务中两套取并集。

### 2. 规则集划分：CL-xx（清理）+ PF-xx（性能）

- `CL-01`~`CL-10`：冗余文件 / 过时符号 / 无用逻辑 / 注释代码块 / 前端不可达文件；
- `PF-01`~`PF-08`：循环内 IO、嵌套循环、全量加载、无界累积容器、循环内字符串拼接、
  热点候选、前端渲染热点、Context 未 memo 化；
- 规则语义与误报边界写入 skill（`.codebuddy/skills/code-cleanup/references/`），
  **阈值唯一真相源**为 `scripts/cleanup/config.py`。

### 3. 独立基线库，**不注册进 quality_gate 的检测器列表**

`scripts/cleanup/` 使用自己的 `scripts/reports/cleanup/cleanup.db`（已 gitignore），
**默认不把清理检测器注册进 `FULL_DETECTORS`**。理由：

- 清理决策由人做出、节奏慢于代码提交，噪声进入 pre-commit 会拖慢开发并诱发"绕过门禁"；
- 两套规则集的误报特征不同，混入同一基线会互相污染 `mark_fixed_missing` 语义。

集成路径（注册方式、差分基线、CI `--strict`）写在 skill 的 `references/integration-guide.md`，
由团队在完成一轮基线收口后再决定是否启用。

### 4. 门禁语义：**建议性优先**

`cleanup.py` 默认退出码 0（只报告）；`--strict` 才在基线外新增项时返回 1。
检测器异常一律 **fail-open**（启发式规则故障不得阻断开发）。
这与 `quality_gate` 的 AP（block）/ OE（guard）分层一致。

### 5. 判定方向：零误报优先

对无法静态证实的场景（字符串反射、装饰器注册、注册表装配、跨仓库消费者、桩代码），
一律**降级为豁免或候选**，宁漏报不误删：

- CL-02 采用「全库词元计数 == 1」而非 AST 引用图，使 `getattr("foo")`、`{"foo": impl}` 等
  字符串动态引用天然兜底；
- CL-02/CL-05 统一经 `names.py` 提取装饰器属性链，豁免 Web 框架路由与框架钩子；
- 删除前的三轮质询（动态引用 / 框架运行时 / 跨仓库与运维）写入 skill 安全协议。

## 后果 (Consequences)

### 正面

- 清理从「一次性人工扫描」变为**可重复、可环比、可追踪生命周期**的机制
  （fingerprint + 基线 + 存量清偿率）；
- 首次全库扫描即产出可执行清单：CL 44 项（CL-01 3 个不可达文件 / CL-02 31 个零引用符号 /
  CL-06 9 处未使用赋值 / CL-07 1 个临时残留）、PF 220 项（含 13 处 ≥3 层嵌套、
  21 处无 LIMIT 全量查询、1 处无界容器）；
- **验证过程反哺共享基础设施**：CL-01 的首次误报（将 `backend/api/main.py` 导入的服务判为不可达）
  暴露了 `quality_gate.ast_utils.read_text_safe` 未处理 UTF-8 BOM 的缺陷 —— 带 BOM 的源文件
  解析失败后 import 边静默丢失，进而影响 `quality_gate` 全部 AST 检测器。
  已改用 `utf-8-sig` 解码并补单测；该修复对两套框架同时生效；
- 性能问题从"等用户反馈"变为"例行巡检 + profiler 实测"的两段式；
- 零新增第三方依赖，纯标准库实现，与 `quality_gate` 共享同一套 AST 索引（全库扫描 2.5s）。

### 负面 / 取舍

- 两套报告（quality_gate / cleanup）需要人工合并，未做统一仪表盘；
- 启发式规则在**首次全库扫描时必然产生大量存量项**（264 项），需要一轮 `--suppress` 收口才能
  进入 `--strict`；在此之前只有趋势价值，没有阻断价值；
- CL-02 刻意不判类方法，类方法死代码需依赖 vulture（外部工具，可选）；
- CL-01 对「休眠运维接口」（Runbook / 快捷方式 / PS1 调用，无 import 边）与仓库外消费者
  （EMSXDataPipeline）无法自动排除，仍需人工核查。

## 备选方案 (Considered Alternatives)

- **方案 A：直接扩写 `quality_gate` 的 OE-xx 规则**，不新建包。
  - 否决原因：清理与性能的判定对象与节奏不同（性能候选需 profiler 复核、清理需人工确认），
    混入同一门禁会让 OE 门禁的"阻断语义"失真；且 `quality_gate` 的 staged 预算（25s）容不下全库图分析。
- **方案 B：引入 knip / vulture / radon 作为唯一手段**，不自研检测器。
  - 否决原因：无法覆盖项目特有语境（模块边界、预计算表约定、多入口前端图、
    本仓库 `data_access/` 只读约束）；且会给仓库引入新的工具链依赖与版本漂移。
  - 采纳部分：外部工具作为**可选增强**列入 `references/tool-matrix.md`，缺失时降级。
- **方案 C：一次性全库清理**（照抄 ADR-0014 的做法）。
  - 否决原因：不可复用、不可环比，问题会随迭代复发；ADR-0014 已证明需要机制化。
- **方案 D：把清理检测器注册进 `FULL_DETECTORS` 统一门禁。**
  - 暂缓原因：会让每次提交都被启发式规则拦截；待存量收口后再由团队决定（预留在集成指南 L1）。

## 相关 ADR

- 关联: [ADR-0014](0014-dead-code-cleanup.md)（死代码清理实践 —— 本机制是其可重复化）
- 关联: [ADR-0016](0016-external-data-store-readonly-split.md)（数据只读分离 —— 清理禁触数据库的红线来源）

## 实施注意事项

- 分支建议: `chore/cleanup-perf-mechanism`
- 交付物：`scripts/cleanup/`（检测器 + CLI + 单测）、`scripts/cleanup.py`（平铺入口）、
  `.codebuddy/skills/code-cleanup/`（SKILL + 规则集 + 安全协议 + 工具矩阵 + 集成指南 + 复盘日志）
- 自测: `python -m pytest scripts/cleanup/tests/ -q`（34 用例，覆盖命中与不误报两侧）
- 实机验证: `python scripts/cleanup.py --report`（全仓 373 文件 / 2.5s）
- 首轮收口顺序：先 `--suppress` 处理误报，再按 B1→B5 分批执行真实清理；
  **本 ADR 只建立机制，不授权执行删除**
