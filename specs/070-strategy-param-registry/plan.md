# 070 — 算法策略参数注册表（含外部白名单接入预留）

> 父计划：`specs/057-execution-decision-loop/plan.md`（DL-16）
> 分支：`070-strategy-param-registry` · worktree：`../EMSXView-wt-070-strategy-param-registry`
> 依赖：DL-04（062，算法族契约——注册表的族字段直接复用）· 消费者：DL-17（硬约束引擎，白名单合规检查的第一个消费方）、DL-18（打分参数化）
> 用户追加要求（2026-10-23）：算法策略预留空间接入外部算法白名单列表作合规检查；白名单格式样板 = `Algo Checklist - 2026-09-02.xlsx`（28 broker × 110 策略名）

## 1. 问题

- **策略参数无单一注册表**：参数经 `strategyParams={strategyName, fields:[{value, disabled}]}` 动态字段流转（broker-strategy-fields.tsx），默认值散落 `route_plans`（`default_strategy_params`/`default_participation_rate`/`default_start_offset_min` 等）与前端常量——新策略接入要改多处，无 schema 校验；
- **合规无白名单机制**：路由提交前无「(broker, algo) 是否在合规准入名单」检查——名单当前是线下 xlsx（Algo Checklist），系统不感知；
- **存量数据无参数版本**：历史订单的策略参数未记录所用注册表/名单版本，事后无法复现路由决策。

## 2. 方案（P2 三栏）

### 2.1 理论依据

策略清单/参数 Schema/默认值/展示顺序集中管理，提交前校验，审计留版本（tasks.md DL-16）；外部算法白名单作合规准入（用户 2026-10-23 追加）。

### 2.2 技术方案（细化到文件与函数）

**注册表契约**（`platform_data/contracts/strategy_registry.py` 新建；纯数据 + 纯函数）：

- `StrategySpec`（frozen dataclass）：`strategy_type`（归一化名）、`display_name`、`family`（DL-04 细分族）、`param_schema`（参数 schema 摘要 dict——字段名/类型/必填/默认值）、`markets`（适用市场族，空=全部）、`sort_order`（展示顺序）
- `STRATEGY_REGISTRY: dict[str, StrategySpec]`：种子策略（VWAP/TWAP/POV/CLOSE/IS/DMA 等核心 ~20 个，spec 的 param_schema 从既有 `strategyParams.fields` 形态抽象：`{"participation_rate": {...}, "start_offset_min": {...}}` 等通用键 + broker 动态字段透传）
- `REGISTRY_VERSION = "strategy-registry-v1"`（结构/种子变更升版）
- `normalize_algo_name(name) -> str`：upper + strip + 去尾点（与 DL-04 同口径）
- `resolve_family(strategy_type) -> str`：归一化名 → DL-04 细分族（白名单 110 名的核心归类表 + DL-04 规则兜底；未归类 → unmapped 显式）
- `validate_strategy_params(strategy_type, params) -> list[str]`：校验纯函数——未知策略/必填缺失/类型不符，返回错误列表（空=通过）
- `default_params(strategy_type) -> dict`：注册表默认值（向后兼容回填用）

**外部白名单接入预留**（同文件，用户追加要求）：

- `AlgoWhitelist`（frozen dataclass）：`brokers: dict[str, frozenset[str]]`（broker → 归一化策略名集合）+ `source_path` + `loaded_at` + `row_count`
- `WHITELIST_PATH_ENV = "EMSXVIEW_ALGO_WHITELIST"`：白名单文件路径（仓库外配置——合规数据不落库、不进 git；支持 .xlsx 样板与等价 .csv）
- `load_algo_whitelist(path: str | None = None) -> AlgoWhitelist | None`：读取 xlsx（`Broker Code` 列 + 横向策略列表，样板格式；`NONE` 单元格忽略）；文件缺失/未配置返回 **None = 未知**（不阻断，只日志）
- `is_algo_whitelisted(whitelist, broker, strategy) -> bool | None`：None = 白名单未知（放行但记录）；True/False = 准入判定
- `compliance_check(whitelist, broker, strategy) -> ComplianceResult`：v0 返回 `(allowed: bool, reason: str)`——allowed=False 仅当白名单已知且 (broker, strategy) 不在名单；reason 可读（"not in algo whitelist" / "whitelist unavailable"）。**DL-17 硬约束引擎的第一个消费方**（本任务只交付检查能力，不接入提交链路阻断——防误阻断存量路由）

**校验服务**（`backend/api/services/strategy_registry.py` 新建）：

- `validate_route_submission(broker, strategy, params) -> SubmissionValidation`：注册表校验 + 白名单检查（白名单配置了才启用）——返回 errors/warnings（warnings 含 unmapped 族、白名单未知）；
- 接入点：`submission_service.submit_proposal_core` 路由前调用——**errors 阻断、warnings 放行 + 审计记录**（存量路由零误阻断）；
- 审计：提交记录（submission 落库处）附 `registry_version` + `whitelist_version`（loaded_at + row_count 摘要）——存量记录缺版本时读取方按「版本未知」处理（不回填伪造）。

**向后兼容**：

- `route_plans` 的 `default_strategy_params` 等字段继续可用；注册表默认值仅在字段缺失时回填（`default_params`），不覆盖显式值；
- 存量订单读取：无参数版本 → 按注册表**当前**默认值回填并在响应标注 `param_source="registry-default"`（可区分显式与回填）。

**测试**（`backend/api/tests/test_strategy_registry.py` + `backend/api/tests/test_algo_whitelist.py` 新建）：

1. 注册表：`normalize_algo_name`（VWAP./TWAP-EU/大小写）、`resolve_family`（白名单 110 名中核心 ~40 个的族归类断言 + unmapped 显式）、`validate_strategy_params`（未知/缺必填/类型错/通过）、`default_params` 回填；
2. 白名单：`load_algo_whitelist`（fixture xlsx：3 虚拟 broker × 少量策略，样板格式；NONE 忽略；大小写归一）、缺失文件 None、未配置 None、`is_algo_whitelisted` 三态、`compliance_check`（allowed/blocked/unknown）；
3. 校验服务：`validate_route_submission`——白名单命中/未命中/未配置三态 + 注册表 error 阻断；
4. 版本常量：`REGISTRY_VERSION` 存在。

### 2.3 检验方法（= 验收标准）

1. 每个启用策略的参数校验测试（用例 1/3）；
2. 存量订单回填可区分（`param_source` 标注，不伪造版本）；
3. 白名单三态行为（命中/未命中/未知）+ 样板格式加载（用例 2）；
4. 提交链路 errors 阻断 / warnings 放行 + 审计留版本（既有 submission 测试不回归）；
5. 既有测试不回归（backend 全量 + boundaries，分进程）。

### 2.4 边界（诚实记录）

- **白名单不接入提交阻断**：v0 只做「检查能力 + 审计记录」——误阻断存量路由的风险高于合规收益；DL-17 硬约束引擎就绪后经特性开关启用阻断（G2：新能力默认关闭）；
- **白名单数据不落库**：文件在仓库外（合规清单由业务维护），系统只读；git 只存样板格式说明与虚拟夹具；
- **注册表种子范围**：核心 ~20 策略入注册表（param_schema 摘要），broker 专有高级算法（Hydra/Escalate 等）经 `resolve_family` 归类但不入 spec（无通用参数 schema）——显式 unmapped/仅族级；
- **存量参数版本不回填**：历史提交无版本记录，标注「未知」而非猜测。

## 3. 规模与拆分说明

预估 diff 约 480 行（注册表契约 ~150 + 白名单 ~90 + 校验服务 ~80 + 接入 ~20 + 测试 ~180）。DL-16 为验收原子单元（注册表 + 白名单预留 + 校验一次交付），沿用单 PR 先例。

## 4. 范围锁

| 动作 | 文件 |
|---|---|
| 新建 | `platform_data/contracts/strategy_registry.py`（注册表 + 白名单契约） |
| 修改 | `platform_data/contracts/__init__.py`（导出） |
| 新建 | `backend/api/services/strategy_registry.py`（校验服务） |
| 修改 | `backend/api/services/submission_service.py`（提交前校验接入，~20 行） |
| 新建 | `backend/api/tests/test_strategy_registry.py`、`backend/api/tests/test_algo_whitelist.py` |
| 新建 | `backend/api/tests/fixtures/algo_whitelist_sample.xlsx`（虚拟 broker 样板夹具） |
| 新建 | `specs/070-strategy-param-registry/plan.md`（本文件） |

范围外（不碰）：前端策略表单改造（保持 `strategyParams.fields` 动态字段透传）、DL-17 硬约束阻断接入、白名单管理 UI（业务线下维护）、`ExecutionView/`。

## 5. 验收（P4）

| 需求（057 DL-16 检验方法） | 覆盖 | 结果 |
|---|---|---|
| 每个启用策略的参数校验测试 | 用例 1/3 | 待实施后回填 |
| 存量订单回填（可区分） | `param_source` 标注 + 用例 | 待实施后回填 |
| 白名单三态 + 样板加载（用户追加） | 用例 2 | 待实施后回填 |
| 提交链路不回归 | submission 既有测试 + 全量 | 待实施后回填 |

## 6. 本次不做

- DL-17 硬约束引擎接入白名单阻断（特性开关默认关闭，G2）；
- 白名单管理界面（线下维护 xlsx）；
- 前端参数表单重构（动态字段透传不变）；
- broker 专有高级算法的完整参数 schema（仅族级归类）。
