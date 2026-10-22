# ADR-0023: 盘中库（intraday store）契约与双仓分工

> 状态: Accepted
> 日期: 2026-10-22
> 标签: architecture, data, backend, deployment

## 背景 (Context)

057 执行决策闭环计划 DL-06（父计划 §4.0 三层时效数据层）需要与 EMSXDataPipeline 联合开发盘中库：管道侧新增盘中调度进程（J1 成交增量/导出入库/运营库采集、J2 收盘后 bar），本侧 MarketView/CostView 只读消费。跨仓协作若不定契约，管道侧按单方理解实现会导致本侧适配器返工；且管道 `SchemaDriftGuard` 对未登记 DDL 会在启动前阻断整条日更——新表必须走注册规范，契约需先冻结「表名 + 列名 + manifest 结构」。

## 决策 (Decision)

1. **盘中库形态**：按交易日分文件 `${EMSXVIEW_DATA_DIR}/intraday/intraday_YYYYMMDD.db`；新鲜度清单 `intraday_manifest.json`（原子写，每数据集 as_of/水位/行数/状态/last_error，与管道 freshness SLA 同口径）。
2. **六张表**（`platform_data/contracts/intraday_store_contracts.py::INTRADAY_TABLES`，列名见 `TABLE_COLUMNS`）：`intraday_fills`、`blotter_snapshots`、`order_intent`、`route_params_snapshot`、`bars_10s_t0`、`snapshot_t0`。管道侧 DDL 与之对齐并经 SchemaDriftGuard 校验。
3. **写入方不变**：管道是盘中库唯一写入方（ADR-0016 对称）；本侧零写入路径（G0）。保留期满**整文件清理**（WRITE 层禁止 DELETE，不在库内删行），v0 定值 30 天。
4. **读侧规则**：`formal-first`——正式库已有该日就用正式数据，否则用盘中库；盘中数据一律标 provisional，临时与正式的差异进守恒审计（沿用已解释缺口机制）；排名/对外结论只用正式数据。
5. **日更复用不碰缺口判定**：J1 不写 `raw_fills`/`fetch_log`，J2 不写 `raw_bdib`——提前写正式表会让当日被当成已完成而跳过（父计划 §4.0 冻结条款）。
6. **库键登记**：`data_access/config.py`（`DB_INTRADAY` / `INTRADAY_DIR` / `INTRADAY_MANIFEST_FILE` / `intraday_db_path()`），两仓常量由契约测试互锁（本侧 `backend/api/tests/test_intraday_store_contract.py` 镜像断言）。

## 后果 (Consequences)

### 正面

- 管道侧 J1/J2（DL-07/08/09）有可校验的契约基准，SchemaDriftGuard 从「阻断风险」变为「对齐工具」；
- 读侧路由/ provisional/守恒审计规则显式化，MarketView/CostView 消费方无需各自解释；
- `order_intent` 列与 DL-01 `OrderIntent` 契约字段一一对应（契约测试锁定），意图口径跨仓一致。

### 负面 / 取舍

- 契约先行意味着 DL-07 之前盘中库不可用（可接受——契约先行是父计划既定流程）；
- 保留期 30 天为 v0 定值（单人单机磁盘压力下的经验值，磁盘紧张时按「调整条件」修订并升 `INTRADAY_STORE_VERSION`）；
- 管道仓库私有，契约执行依赖管道侧排期（父计划 §8 跨仓依赖风险的对策：契约先行 + 技术文档同步 + 复验）。

### 对其他 ADR 的影响

- 引用: ADR-0016（外部数据存储只读拆分——本 ADR 是其「分析库只读」在盘中库的对称扩展）、ADR-0022（运营库 SQLite——盘中库与分析库/运营库三方分工中的一环）
- 被引用: 后续 ADR（DL-07 就绪后的只读适配器、保留期调整、综合评分权重启用等）

## 备选方案 (Considered Alternatives)

- 方案 A: 单库 + 行级 provisional 标记（不分文件）
  - 否决原因: 与既有分析库混库会触发 SchemaDriftGuard 对既有库的漂移扫描面；保留期满清理在单库内需要 DELETE（WRITE 层禁止）——分文件整清是唯一兼容形态
- 方案 B: 先实现管道侧后补契约
  - 否决原因: 父计划 §4.0 明确「契约先行」；漂移后返工成本高于契约先行（且 SchemaDriftGuard 会在管道启动前阻断未注册 DDL，反而更慢）
- 方案 C: 盘中库放运营库（backend SQLite）
  - 否决原因: 违反「管道是数据层唯一写入方」与 ADR-0016 的分工；运营库写入方是后端进程，J1/J2 在管道侧，跨进程写同一库违背单写者模型

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件: `platform_data/contracts/intraday_store_contracts.py`（契约源）、`data_access/config.py`（库键）、`backend/api/tests/test_intraday_store_contract.py`（镜像断言）
- 管道侧协作（T3/T4/T7，指南 §13）: 按其仓库规范实现 J1/J2 时以本契约为准；新表 DDL 走 schema 注册与迁移规范；改动后按指南 §13 更新 `docs/EMSXDataPipeline-TECHNICAL_GUIDE.md` 并同步本仓库副本
- 回滚策略: 契约升版（`INTRADAY_STORE_VERSION`）而非删表；管道侧特性开关默认关闭（父计划 G2：新能力默认关闭、按市场逐个开启）
- 保留期调整条件: 磁盘持续紧张（intraday 目录 > 阈值）或消费方需要更长回看窗口时，修订常量并升版，两仓同步

## 验证记录 (Verification Log)

- [x] 契约镜像测试通过（12 用例，2026-10-22，065 PR）
- [ ] 管道侧 DDL 注册 + SchemaDriftGuard 通过（DL-07/08 管道实施时）
- [ ] 两仓契约测试互锁（管道侧镜像就绪后）
