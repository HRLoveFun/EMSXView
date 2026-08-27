# 数据更新管道健壮性机制（Pipeline Resilience）

> 来源：对数据更新管道（`CostView/scripts/daily_update.py` + `DataPipeline/orchestration/`）
> 历史问题的系统复盘（2026-04 ~ 2026-08），归纳为 6 类故障模式与配套机制。
> 证据源：AGENTS.md 计划记录、`docs/archive/` 诊断报告、git 提交历史、生产日志
> （`logs/pipeline/fillfetch.log`、`logs/pipeline/guardrail/*.jsonl`）。
> Created: 2026-08-26 · 维护规则：每次管道事故复盘后更新对应故障模式条目

---

## 1. 历史问题档案（按故障模式归类）

### A. 静默失败类 —— 危害最大，共同特征是「状态绿色但数据缺失」

| # | 时间 | 问题 | 根因 | 当时处置 | 暴露的缺口 |
|---|------|------|------|---------|-----------|
| A1 | 2026-07-03 | S2 跨日维度错位：13 个 source_date 共 **360 万+ 行静默未处理** | `target_dates` 用拉取日而非真实交易日维度；写入前校验不一致时**整批拒绝**且无告警 | 改维度为 `DISTINCT order_as_of_date` + `reprocess_affected_dates.py` 回填 | 缺失靠人工对账才发现；整批拒绝放大单点错误 |
| A2 | 2026-08-21 | fill fetch 失败但最终报 success（前端绿灯） | fetch 失败不传导到最终 status；fetch 失败 + BDIB 成功 = 绿色 | `_fetch_failure_detail()` 显式传导 → exit 1 → 前端红标 | 该模式**只覆盖了 fill fetch 一个阶段** |
| A3 | 2026-08-26 | **S5 BDIB 全量静默短路**：`raw_bdib_rows=0` 却报 `completed:true, status:success`，raw_bdib.db 停更 | 分区迁移在 processed_fills.db 残留 0 行空壳表（`ticker_repository` 等 3 张）；`fills.py::_conn_for` B4 自动检测**只判断表存在不判断是否有数据** → `get_ticker_exchange_map()` 路由到空壳表返回 `{}` → stages_process.py:283 早退分支裸 return | 待修复（见 §4 M1/M3） | 「依赖输入为空」与「真的没活干」在 summary 中不可区分；health_check 查不出这类逻辑短路 |

### B. 配置 / 契约漂移类

| # | 时间 | 问题 | 根因 |
|---|------|------|------|
| B1 | 2026-07-08 | 549 个 ticker 有成交无 BDIB 行情，其中 **424 个**因 `Config.BDIB_EXCHANGE` 白名单缺 9 个交易所 | 白名单手工维护，与 `ticker_registry.exchange` 实际分布脱节 |
| B2 | 2026-07-08 | 108 个 ticker 未注册到 `ticker_repository` | 注册流程与使用方无一致性校验 |
| B3 | 2026-08-26 | 见 A3 —— 空壳表残留即迁移契约未闭合 | 分区迁移无「退役清理」收尾步骤 |
| B4 | 持续 | schema drift 白名单容忍 `route_event_history.event_id` 类型漂移降级 INFO | 已知漂移无清零 SLA，永久容忍 |
| B5 | 2026-06 | deps 重构后 repository 方法悬空引用（提交 faf26b1/dc9a7f8/79c416f 补 12 个漏迁移方法） | 重构后接口契约无自动核对 |

### C. 数据语义 / 质量类

| # | 时间 | 问题 | 根因 |
|---|------|------|------|
| C1 | 2026-08 | `tca_route_summary.fx_rate` 大面积 NULL，USD 成交金额暂按 1.0 兜底（fx_coverage=0） | S5.5 未回填历史；兜底值污染下游统计 |
| C2 | 2026-08 | KS 市场 TCA 金额虚高至 16.74B | 复合币种 `str.contains("USD")` 误匹配被强制置 1.0 → 已改精确匹配 `USD CURNCY`，NULL 保持 NULL |
| C3 | 2026-05 前 | RouteId/FillId int/str 漂移（055e0db）、`order_as_of_date` 格式不一致、GetFillsResponse 嵌套解析错误（612b8b0） | 外部数据格式假设分散在各处，未集中到 Config 单一来源 |

### D. 外部依赖约束类

| # | 时间 | 问题 | 处置 |
|---|------|------|------|
| D1 | 持续 | Bloomberg BDIB 日内柱保留窗口 ~180 天（部分市场仅 6 个月），**超窗永久无法回补** | `backfill_bdib_by_market.py` 默认 start=today-180（`Config.BDIB_API_RETENTION_DAYS`）；教训：数据更新延迟 = 永久损失，新鲜度是硬约束 |
| D2 | 2026-08 | Bloomberg 配额爆满导致拉取静默返回空 | 005 计划：quota_pause 感知 + 自动暂停/恢复 + FX 最近已知汇率降级 |
| D3 | 持续 | 17 个 ticker BDIB API 确认无数据反复重试 | `outdated_tickers.json` 标记豁免 |

### E. 性能 / 体积治理类

| # | 时间 | 问题 | 影响 |
|---|------|------|------|
| E1 | 2026-07-16 | TCA 查询请求时实时聚合订单层级指标 | 大数据量高延迟 → 改 `tca_route_summary` 管道预计算 |
| E2 | 2026-08-26 | S5 前置守卫 EmptyBarGuard 全表扫描 78GB raw_bdib.db 耗时 **13.6 分钟** + CoverageGuard 4.8 分钟 | 前置校验串行阻塞关键路径 18 分钟 |
| E3 | 持续 | raw_bdib.db 78.69GB 远超 5GB 告警阈值，**只有告警没有动作** | 体积治理开环 |
| E4 | 历史 | 前端 watchdog 将长阻塞段（归档 7 库 + VACUUM）误判 stalled | `[STAGE]` 心跳协议缓解，但守卫扫描段仍无心跳 |

### F. 平台异质 / 环境类

| # | 问题 | 处置 |
|---|------|------|
| F1 | Windows cp1252 控制台中文 UnicodeEncodeError；管道重定向时 reconfigure 抛 OSError | daily_update.py 双分支 UTF-8 包装（已固化） |
| F2 | 子进程写入驻留 WAL，`mode=ro` 只读连接读不到新数据 | `_checkpoint_wal()` 强制 TRUNCATE checkpoint（已固化） |
| F3 | subprocess `capture_output=True` 在 Windows 管道缓冲区满时死锁 | 改临时文件收输出（已固化，见 `_run_b4_observation_step` 注释） |
| F4 | AP-16 启动器路径少算一层 → 120s 黑盒超时 + 错误日志误导排查 | `.emsxview-root` marker + fail-fast 自检（已固化） |

### G. 回归防护缺失类

| # | 问题 | 处置 |
|---|------|------|
| G1 | backend 测试腐化 26 项累积数月，CI 接入 boundary-protection 后才爆发（004 计划） | CI 全量测试恢复硬阻断 |
| G2 | 归档/VACUUM 长操作被 watchdog 误杀 | `[STAGE]` 心跳 + vacuum 前置 marker |

---

## 2. 现有机制盘点（避免重复建设）

| 层 | 已有机制 | 位置 |
|----|---------|------|
| 护栏框架 | GuardPipeline：run_id 隔离三态熔断器、Pydantic v2 阶段输入输出校验、S1 宽松/S2+严格策略、JSONL 结构化运行日志 | `orchestration/guard.py`、`monitoring/run_logger.py`、`validation/` |
| 专项守卫 | empty_bar_guard / bdib_coverage_guard / schema_drift_guard | `pipeline_guards/` |
| 外部依赖 | quota_pause 配额暂停、fx_rates 持久化+最近已知汇率降级、permanent_gap_dates 永久缺口豁免、outdated_tickers | `common/quota_pause.py`、`acquisition/fx_fetcher.py`、`common/permanent_gap_dates.py` |
| 失败传导 | `_fetch_failure_detail` → status=failed → exit 1 → 前端红标 | daily_update.py:369 |
| 运维基建 | `[STAGE]` 心跳、WAL checkpoint、条件 VACUUM、归档、DB 体积告警 | daily_update.py |
| 健康监控 | health_check.py（DB 体积/WAL/完整性/TCA 延迟）、check_trs/monitor_trs | scripts/ |
| CI 门禁 | boundary.yml backend 全量测试硬阻断、文档漂移审计 | .github/workflows/ |
| 运维脚本 | backfill_bdib_by_market / backfill_ticker_repository / reprocess_affected_dates 等 | scripts/ops/ |

---

## 3. 归纳：六类故障模式 → 六大健壮性机制

```
故障模式                    →   机制
A 静默失败                  →   M1 失败显式化（最高优先级）
A(对账发现)/B               →   M2 存量对账与新鲜度 SLA
B 配置/契约漂移             →   M3 漂移防护
C 语义质量 / D 外部约束     →   M4 外部依赖韧性（大部分已有，固化+推广）
E 性能体积                  →   M5 性能与体积治理闭环
A3/E2 排障困难              →   M6 可观测性与一键诊断
```

### M1 失败显式化（Anti-Silent-Failure）★ 最高优先级

> 原则：**任何「跳过/短路/零产出」都必须可区分、可归因、可上报**。
> 状态绿色必须等价于「数据确实更新了」。

- **M1.1 零产出断言**：候选日期 > 0 且写入行数 = 0 时，禁止裸 `return True`。
  短路路径必须在 summary 携带 `short_circuit_reason` 字段并记 WARNING 进护栏日志。
  落地点：`stages_process.py::IntegrateBDIBStage.process` 的全部早退分支（A3 即此漏洞）。
- **M1.2 失败传导全覆盖**：把 `_fetch_failure_detail` 模式推广到所有阶段——
  bdib / route_metrics / daily_metrics 的 failed_dates、failed_chunks、quota_paused
  均参与最终 status 判定，而不仅是 fill fetch。
- **M1.3 依赖预检 fail-fast**：阶段前置依赖异常（如 ticker 映射为空、依赖表 0 行）
  视为**阶段失败**而非静默跳过。「上游真没数据」与「我的输入坏了」语义必须分开，
  后者直接 fail 并阻断后续依赖它的阶段。
- **M1.4 summary 契约固定**：每阶段 summary 必填
  `candidate_dates / processed / skipped{with_reason} / failed / rows_written`，
  缺字段视为护栏违规（可加入 schema_drift_guard 同级的静态检查）。

### M2 存量对账与新鲜度 SLA

> 原则：**缺失不能靠人眼发现**。360 万行静默缺失（A1）与 2 天停更（A3）
> 都应被每日自动对账捕获。

- **M2.1 跨库行数守恒日检**：raw_fills ↔ processed_fills ↔ agg_fills ↔ fill_bdib
  按 order_as_of_date 对账，gap > 0 即告警（S2 修复时已建脚本基础，需常态化为日更收尾步骤）。
- **M2.2 新鲜度 SLA 校验**：daily_update 收尾时校验各核心库
   `MAX(order_as_of_date)` 与今日之间「缺失的交易日数」超阈值即 status=failed。
   **以交易日（工作日）为单位**规避周末误判（周一跑批数据到周五属正常）；
   阈值 `FRESHNESS_WARN_BUSINESS_DAYS`(默认1，仅告警) / `FRESHNESS_FAIL_BUSINESS_DAYS`(默认2，失败)；
   配额暂停期间（`is_quota_paused`）跳过，避免合法跳过被误判。受检库：
   raw_fills / processed_fills / raw_bdib / fill_bdib（列 `order_as_of_date`）。
   *该校验可直接捕获 A1、A3 两起事故；实现位于 `CostView/scripts/daily_update.py::
   _freshness_failure_detail` + `summary["freshness"]`，已带单测
   （`test_daily_update_fetch_failure.py` 的 `test_freshness_*`）。*
- **M2.3 覆盖率守卫升级**：BDIBCoverageGuard 结果从 warning 升级为进入
  summary 失败清单（参与 M1.2 传导），杜绝「79 个 ticker 无行情」长期滞留 WARN。

### M3 漂移防护（配置 / 迁移契约）

> 原则：**单一真相源 + 周期性一致性 diff**；迁移必须以「退役清理」收尾。

- **M3.1 表退役 checklist**：分区迁移完成的旧表必须 drop 或 rename 归档；
  `_conn_for` 类自动检测路由改为「表存在 **且非空壳**」或引入迁移注册表标记，
  禁止以表存在性作为唯一判据（B3/A3 根因）。
- **M3.2 白名单 ↔ 实际分布 diff 审计**：周期任务对比 `Config.BDIB_EXCHANGE`
  与 `ticker_registry.exchange` 分布，白名单外出现成交数据的交易所自动告警
  （B1 的 424 个 ticker 本可由此发现）。同型审计适用于一切白名单类配置。
- **M3.3 已知漂移清零 SLA**：schema drift 白名单条目必须挂修复事项与期限，
  防止 B4 式永久容忍。
- **M3.4 CI 回归门禁维持**：backend 全量测试硬阻断（004）不许再松绑；
  管道核心路径（orchestration/storage）改动须带回归测试。

### M4 外部依赖韧性（固化既有实践为约定）

> 原则：**外部不可控 → 降级阶梯必须显式，禁止魔法值兜底**。

- **M4.1 配额感知**：quota_pause 暂停/恢复（已有）。
- **M4.2 降级阶梯**：API 失败 → 重试(退避) → 最近已知值 → 显式 NULL + 标记。
  禁止用 1.0 之类魔法值兜底（C1/C2 教训：兜底值污染下游统计且极难追溯）。
- **M4.3 不可回补缺口登记豁免**：permanent_gap_dates / outdated_tickers 模式
  推广到所有「外部确认无数据」场景，避免无效重试与重复排查。
- **M4.4 外部窗口内建**：类似 BDIB 180 天保留窗口的硬约束，必须编码为
  Config 常量并成为相关工具默认值（D1：延迟即永久损失）。

### M5 性能与体积治理闭环

- **M5.1 守卫轻量化**：前置守卫改增量扫描（只扫新增日期）或移出关键路径
  并行执行；扫描加超时与采样上限（E2：18 分钟串行阻塞不可接受）。
- **M5.2 体积告警 → 动作联动**：超阈值触发归档/VACUUM/清理动作而非仅 warning；
  条件 VACUUM 从 processed_fills 单库推广（E3：raw_bdib 78.69GB 开环）。
- **M5.3 长阻塞段心跳**：任何预计 > 60s 的段必须有 `[STAGE]` 心跳（E4/G2）。

### M6 可观测性与一键诊断

- **M6.1 health_check 扩展逻辑检查项**：新鲜度（M2.2）、空壳表探测（M3.1）、
  映射非空（M1.3）、覆盖率摘要（M2.3）——当前 health_check 只查物理健康，
  A3 这类逻辑短路完全不可见。
- **M6.2 一键预检脚本**：`scripts/ops/pipeline_preflight.py` 汇总 M1-M3 检查项，
  日更前/排障时一条命令输出全量结论。
- **M6.3 运行摘要增强**：短路 reason 与 per-date 明细持久化到 guardrail JSONL，
  保证事后可从日志单点还原决策链。

---

## 4. 落地路线图

| 优先级 | 事项 | 对应机制 | 关联事故 | 状态 |
|--------|------|---------|---------|------|
| **P0（立即）** | 清理 processed_fills.db 空壳表（8 张，`drop_partition_shell_tables.py`）+ `_conn_for` 非空壳判断 | M3.1 | A3 | ✅ 2026-08-26 |
| **P0（立即）** | S5 早退分支加 short_circuit_reason + WARNING | M1.1 | A3 | ✅ 2026-08-26 |
| **P0（本周）** | daily_update 收尾加新鲜度 SLA 校验 | M2.2 | A1/A3 | ✅ |
| P1 | 失败传导推广至全部阶段；summary 契约固定 | M1.2/M1.4 | A2 | ✅ `_stage_failure_detail` 递归扫描任意阶段 `short_circuit_reason`（含嵌套） |
| P1 | 依赖预检 fail-fast（空映射即阶段失败） | M1.3 | A3 | 🔶 软失败（status=failed + exit 1）已落地；硬阻断（raise/abort 中断后续阶段）暂缓——生产硬中断风险高，违背 G0 数据零受损（下游存量处理仍有益），待评审 |
| P1 | 守卫增量化/移出关键路径 | M5.1 | E2 | 🔶 新鲜度 SLA（M2.2）+ 白名单 diff（M3.2）已移至 WAL checkpoint 之后非关键路径；按基线增量复用、避免全表重复扫描待评估 |
| P1 | 白名单 ↔ 分布 diff 审计 | M3.2 | B1/B2 | ✅ `pipeline_guards/exchange_whitelist_audit.py::audit_exchange_coverage`，仅告警不阻断，写 `summary["exchange_diff"]` |
| P2 | 跨库守恒对账常态化 | M2.1 | A1 | ✅ `pipeline_guards/cross_db_conservation.py::audit_conservation`，日更写 `summary["conservation"]` |
| P2 | health_check 逻辑检查项 + preflight 脚本 | M6.1/M6.2 | A3 | 🔶 M6.1 落地：`health_check.py` 增 freshness/shell_tables/exchange_diff/conservation 逻辑检查；preflight 独立脚本待评估 |
| P2 | 体积告警→动作联动 | M5.2 | E3 | 🔶 `health_check.py::_check_volume_growth` 对比上次快照超阈值告警（动作联动监控侧，自动化动作待评估） |
| P2 | drift 白名单清零 SLA | M3.3 | B4 | 🔶 流程侧：schema_drift_guard 白名单条目须在 PR 描述挂修复事项+期限；CI 门禁维持（004），自动化清零待评估 |

> **P0 执行记录（2026-08-26）**：
> - `scripts/ops/drop_partition_shell_tables.py` 清理 processed_fills.db 中 8 张空壳表
>   （DDL 审计 manifest 见 `logs/pipeline/drop_partition_shell_tables_*.json`）
> - `fills.py::_conn_for` 空壳检测：legacy 表存在但 0 行同样路由分区库
>   （回归测试 `tests/storage/test_partition_shell_routing.py`）
> - `stages_process.py::IntegrateBDIBStage` 空映射短路携带 `short_circuit_reason`
> - `daily_update.py::_stage_failure_detail` 将阶段短路传导为 status=failed + exit 1
>   （回归测试追加于 `tests/guardrail/test_daily_update_fetch_failure.py` 场景 4）
> - **M2.2 新鲜度 SLA 落地**：`Config.FRESHNESS_WARN_BUSINESS_DAYS`(1)/`FRESHNESS_FAIL_BUSINESS_DAYS`(2)
>   以「交易日」为计量；`daily_update.py::_freshness_failure_detail` 收尾校验
>   raw_fills/processed_fills/raw_bdib/fill_bdib，缺失 >2 交易日即 status=failed；
>   配额暂停跳过；`summary["freshness"]` 记录；`run_daily_pipeline(freshness_check=)` 可注入。
> - 端到端验证：修复后日更 raw_bdib 写入 5,582,863 行（20260824+20260825），
>   fill_bdib 集成 68,724 行；测试 DataPipeline 222 passed（含 5 项新鲜度） / CostView 相关 28 passed
>
> **P1 执行记录（2026-08-26）**：
> - **M1.4 失败传导推广**：`daily_update.py::_stage_failure_detail` 改为递归
>   `_scan_short_circuit`，扫描管道 summary 内任意阶段（含嵌套子字典）的
>   `short_circuit_reason`，不再仅限 `bdib`（机制通用化，后续阶段只需在
>   summary 携带 `short_circuit_reason` 即自动传导 failed）。
> - **M3.2 白名单 diff 审计**：新增 `DataPipeline/pipeline_guards/exchange_whitelist_audit.py::
>   audit_exchange_coverage`，对比 `Config.BDIB_EXCHANGE` 与 `processed_fills.Exchange`
>   实际分布，输出 `outside_whitelist`（数据有但白名单遗漏 → B1 类静默缺失根因）与
>   `whitelisted_no_data`（信息项）；在 `daily_update.py` 收尾以仅告警、不阻断方式
>   写入 `summary["exchange_diff"]`。
> - 测试：`tests/guardrail/test_daily_update_fetch_failure.py` 加 7 项
>   （M1.4 递归/嵌套/clean + M3.2 检出/一致）；DataPipeline 全量 **227 passed**。
> - **M1.3 决策**：保留软失败（status=failed + exit 1），不升硬阻断——生产硬中断会
>   中断下游存量处理，违背 G0 数据零受损，待专项评审。
> - **M5.1 部分**：新鲜度 SLA 与白名单审计均置于 WAL checkpoint 之后非关键路径；
>   按基线增量复用（避免全表重复扫描）待后续评估。

> **P2 执行记录（2026-08-26）**：
> - **M2.1 跨库守恒**：新增 `DataPipeline/pipeline_guards/cross_db_conservation.py::
>   audit_conservation`（按 `order_as_of_date` 比对 raw_fills↔processed_fills、
>   raw_bdib↔fill_bdib 整日缺失），`daily_update.py` 收尾仅告警写入
>   `summary["conservation"]`。
> - **M6.1 逻辑检查**：`scripts/health_check.py` 新增 `freshness` / `shell_tables` /
>   `exchange_diff` / `conservation` 四项逻辑检查（空壳表复用 `_PARTITION_DB_MAP`
>   真相源探测）；quick 模式跳过 conservation（全表扫描较重）。
> - **M5.2 体积增长**：`health_check.py::_check_volume_growth` 对比上次健康快照
>   `HEALTH_MANIFEST` 单库增量超 `HEALTH_DB_GROWTH_GB`(默认5) 告警。
> - **M3.3 / M1.3 / M5.1 收尾**：均标注为流程/监控侧 SLA，自动化动作与硬阻断
>   待专项评审（不破坏 G0 数据零受损）。
> - 测试：`tests/guardrail/test_pipeline_resilience_p2.py` 4 项
>   （守恒均衡/缺失 + health_check 逻辑方法/run 注册）；DataPipeline 全量随 P0/P1 共
>   **227+ 通过**（含本批 P2 测试）。

---

## 5. 维护约定

- 每次管道事故复盘：在本文件 §1 追加条目（编号续排），并在 §3 对应机制标注验证点。
- 机制变更走 PR review；与本文件冲突的新代码设计应在设计评审期对齐。
- 关联文档：`plan-design-principles.md`（G0-G3 门控）、`anti-patterns.md`（AP 清单）、
  `docs/archive/2026-08-26/002-pipeline-guardrail/research.md`（护栏框架原始设计）。
