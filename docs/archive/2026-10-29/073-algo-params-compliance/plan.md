# 073 — 算法参数合规层（DL-17c）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-17 拆分第三层）
> 分支：`073-algo-params-compliance` · worktree：`../EMSXView-wt-073-algo-params-compliance`
> 依赖：DL-16（070 注册表+白名单）、DL-17a（071 准入）、DL-17b（072 订单合规）、DL-03（061 会话/竞价）· 消费者：DL-18（参数策略 v0）
> 交易员意见第 11–14 项（2026-10-23 修订版）；用户补充：「每个券商的具体精度使用已有记录」

## 1. 问题

- **白名单未知放行**（DL-16 v0 语义）：`compliance_check` 在白名单未配置时返回 `allowed=True`——交易员要求「未命中/未知均不放行、转人工」；
- **volume cap 无校验**：EMSX 路由必须携带 volume cap（参与率上限），系统当前不检查是否带、不带也照发；各券商对该参数的命名不一致（`PctVol`/`MaxPctVol`/`VolumeCap` 等），需映射；
- **volume cap 无分配规则**：同日同名（同标的）多笔订单共享总额度（非 EUR 18.0、EUR 9.0），当前无按数量比例的分配逻辑——各自独立设定会导致加总超配；
- **收盘拍卖订单无 release time 约束**：订单过早到达券商会暴露交易方向，交易员要求必须携带 release time。

## 2. 方案（P2 三栏）

### 2.1 理论依据

「游戏规则」显式化为硬约束（057 plan §理论依据）；参数合规是路由指令正确性的最后一道闸（交易员意见第 11–14 项）；volume cap 总额度共享 = 组合级约束而非订单级（用户口径）。

### 2.2 技术方案（细化到文件与函数）

**契约**（`platform_data/contracts/algo_params.py` 新建；纯数据 + 纯函数）：

- `MAX_VOLUME_CAP_NON_EUR = 18.0` / `MAX_VOLUME_CAP_EUR = 9.0` / `VOLUME_CAP_PRECISION = 0.1` / `ALGO_PARAMS_VERSION = "algo-params-v1"`
- `VolumeCapPolicy`：`max_cap_for(currency_or_market) -> float`（EUR 判定：currency 为 EUR 或 market 折叠为 EU → 9.0，否则 18.0）；`param_name_for(broker) -> str`（券商映射，缺省 `PctVol`）
- `allocate_volume_caps(legs: list[tuple[order_id, qty]], max_cap: float) -> dict[order_id, float]`：
  - 同组按数量比例分配：`cap_i = floor(qty_i / Σqty × max_cap / 0.1) × 0.1`（**向下取整到 0.1，保证 sum ≤ cap**）；
  - 剩余额度（因取整损失）分配给数量最大的一单（仍 ≤ cap）；
  - 单笔 qty=0 或组内 Σqty=0 → 返回空（调用方转人工）。
- `release_time_required(market_code: str) -> bool`：收盘拍卖市场判定（DL-03 注册表 + `EARLY_CLOSE_AUCTION_EXCHANGES`）
- `check_volume_cap_present(params: dict, broker: str, policy) -> list[str]`：按券商命名映射查找参数；缺失返回错误
- `check_release_time_present(params: dict, market_code: str) -> list[str]`：收盘拍卖市场要求 `release_time` 参数

**券商参数命名与精度的既有记录复用**（用户 2026-10-23 口径）：

实测（2026-10-23）：
- `backend/api/data/broker_algorithms.json` 的 `strategies[].parameters` 结构存在但**当前缓存为空**（29 个 broker 的 strategies.name/parameters 均未填充——EMSX 菜单刷新后会填充）；
- `backend/api/data/broker_hand_instruction.json` 是仓库既有的「**每券商 → 单个值**」JSON 映射记录（HAND_INSTRUCTION，手工维护、`_comment` 说明「Omitted brokers default to 'ANY'」）；
- `tca_route_summary` / EMSX 导出均无 volume cap 参数列。

实现口径：
- **命名映射沿用 `broker_hand_instruction.json` 同款模式**：新增 `backend/api/data/broker_volume_cap_params.json`（`{broker: param_name}`，`_comment` 说明缺省 `PctVol`），与 hand_instruction 并排放置、同款加载方式；
- 优先从 `broker_algorithms.json` 的 parameters 结构读取（若已填充，按参数名含 `vol`/`pct` 关键字匹配）；两者皆无 → 缺省 `PctVol` 并在检查结果标注 `param_name_source="default"`（可观测，不静默）；
- **精度 0.1 为契约常量**（`VOLUME_CAP_PRECISION`），不按券商区分——用户「精度已有记录」指参数命名/取值惯例，分配算法统一按 0.1 步进（交易员意见原文：「精确到小数点后 1 位」）。

**白名单语义修订**（DL-16 v0 → v1）：

- `PlatformData/contracts/access_policy.py::PolicyBundle.configured=False`（策略文件未配置）→ **保持跳过**（部署初期不误伤，071 已定）；
- `compliance_service`/DL-16 的「白名单未配置（未设置 `EMSXVIEW_ALGO_WHITELIST`）→ warning 不阻断」**改为阻断**：`ALGO_WHITELIST_UNKNOWN`（BLOCK，转人工）——交易员要求「未知不放行」；
- 同步修订 `test_strategy_registry.py::test_no_whitelist_warns_not_blocks` 等 3 个用例（行为变更显式记录在 PR）。

**接入**：

- `services/order_compliance_service.py::evaluate_order_compliance` 扩展（072 的既有共用入口）：增加 `check_volume_cap_present` + `check_release_time_present`（params 取自 `proposal["strategy_params"]`）→ BLOCK；
- `submission_service` / `orders_crud.route_order` 无需新增接入点（复用 072 的统一入口）；
- **volume cap 分配**：`build_volume_cap_plan(legs, currency)` 作为服务能力交付（EV 批量路由在生成子路由时调用），v0 不自动改写既有参数——只提供分配计划 + 校验（违反 BLOCK）。

**测试**（`backend/api/tests/test_algo_params.py` 新建）：

1. `allocate_volume_caps`：等比分配、0.1 向下取整守恒（sum ≤ cap）、余数给最大单、单笔/零量边界；
2. EUR 与非 EUR 上限（`max_cap_for`：currency=EUR / market 折叠 EU → 9.0，其余 18.0）；
3. `param_name_for`：JSON 映射命中 / 缺省 `PctVol` / 来源标注；
4. `check_volume_cap_present`：参数在/缺失/空值；
5. `release_time_required`：收盘拍卖市场（US/JP 等）True、非收盘市场 False；
6. `check_release_time_present`：收盘拍卖缺失 → 错误；非收盘市场不要求；
7. 白名单未知语义：`validate_route_submission` 未配置白名单 → BLOCK（更新既有 3 用例）；
8. 既有不回归（backend 全量 + boundaries）。

### 2.3 检验方法（= 验收标准）

1. 分配守恒与精度单测（加总 ≤ 上限、0.1 步进、比例正确）；
2. 券商命名映射：既有 JSON 命中、缺省回落且来源可观测；
3. 白名单「未命中/未知」均不放行（BLOCK 转人工）——含既有用例修订；
4. release time：收盘拍卖市场必带、缺失阻断；
5. 既有全量不回归。

### 2.4 边界（诚实记录）

- **volume cap / release time 检查经特性开关**（`EMSXVIEW_ALGO_PARAMS_ENFORCED`，默认关闭，G2）：既有路由大多未带 volume cap，直接阻断会使系统停摆——默认不检查，开启后 BLOCK；白名单「未命中/未知不放行」不走开关（交易员明确语义，部署配置白名单后即生效）；
- **不自动改写券商参数**：v0 只校验 + 出分配计划（BLOCK 违规），参数落库/下发由既有路由流程负责——「禁止自行创建订单」纪律的延伸；
- **`broker_algorithms.json` parameters 当前为空**：命名映射以 hand_instruction 同款 JSON 为主，EMSX 菜单刷新后自动优先读取（读取逻辑已实现，不需改动）；
- **`backend/api/data/` 整体 gitignore**（运行时数据目录）：`broker_volume_cap_params.json` 与 `broker_hand_instruction.json` 同款，由部署机手工维护，模板：`{"_comment": "...", "EQ-JPM": "MaxPctVol", "EQ-MS": "PctVol"}`；不进 git、缺失回落缺省；
- **volume cap 组的界定（2026-10-23 用户确认）**：同日同名**且同方向**——按 `(equ_ticker, side)` 分组；同日同名不同方向先走 072 的反向单轧差，因此进入参数分配阶段时只会存在同方向订单；
- **release time 参数名**：固定 `release_time`（EMSX 惯例），不做券商映射（交易员意见未要求）。

## 3. 规模与拆分说明

预估 diff 约 430 行（契约 ~150 + 命名映射 JSON ~30 + 服务接入 ~40 + 测试 ~170 + 白名单语义修订 ~40）。073 为 DL-17c 的验收原子单元。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/algo_params.py` |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 部署侧 | `backend/api/data/broker_volume_cap_params.json`（每券商参数名映射；**`backend/api/data/` 整体 gitignore，部署机手工维护**，模板见 §2.2；缺失时回落缺省 `PctVol` 且检查结果标注 `name_source=default`） |
| 修改 | `backend/api/services/strategy_registry.py`（白名单未知 → BLOCK） |
| 修改 | `backend/api/services/order_compliance_service.py`（volume cap + release time 检查接入） |
| 修改 | `backend/api/schemas/batch.py`（Violation code 扩展：VOLUME_CAP_MISSING / RELEASE_TIME_MISSING / ALGO_WHITELIST_UNKNOWN） |
| 修改 | `backend/api/tests/test_strategy_registry.py`（3 个用例语义更新） |
| 新建 | `backend/api/tests/test_algo_params.py` |
| 新建 | `specs/073-algo-params-compliance/plan.md`（本文件） |

范围外（不碰）：`MarketView/`、`CostView/`、EV 前端（volume cap 编辑器）、DL-18 参数策略、券商参数自动刷新作业。

## 5. 验收（P4）

| 需求（交易员意见 11–14 项） | 覆盖 | 结果 |
|---|---|---|
| 券商算法白名单未命中/未知不放行 | `strategy_registry` 语义修订 + 用例 7 | 待实施后回填 |
| 每路由必带 volume cap（含命名映射） | `check_volume_cap_present` + `param_name_for` + 用例 3/4 | 待实施后回填 |
| volume cap 分配（比例/精度/上限/重算） | `allocate_volume_caps` + 用例 1/2 | 待实施后回填 |
| 收盘拍卖 release time 必带 | `check_release_time_present` + 用例 5/6 | 待实施后回填 |
| 既有不回归 | backend 全量 + boundaries | 待实施后回填 |

## 6. 本次不做

- DL-18（参数策略 v0：起止时间/参与率上限/urgency→参数模板）；
- EV 前端 volume cap 可视化编辑；
- 券商参数缓存自动刷新作业（EMSX 菜单刷新由既有链路负责）；
- volume cap 参数的实际下发改写（只校验 + 出计划）。
