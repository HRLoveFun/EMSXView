# Schema Contract — Frontend TypeScript ↔ Backend Python

> L2 | 权威：跨模块 TS↔Python 类型契约（Contract 1–4） | 不权威：HTTP 端点清单（见 `docs/api-contracts.md`）

This document defines the canonical data types that cross the HTTP/WS boundary
between the React frontend and FastAPI backend. Both sides maintain independent
type definitions that MUST stay in sync with this contract.

## Contract Versioning

Each contract has a version string (e.g. `v1`). Breaking changes require a
version bump and a migration period where both old and new formats are accepted.

| Contract | Version | Python Source | TypeScript Source |
|---|---|---|---|
| Handoff Metadata | v1 | `platform_data/contracts/handoff_contracts.py::HandoffMetadata` | `handoff-api.ts::HandoffMetadata` |
| Market→Execution | v1 | `platform_data/contracts/handoff_contracts.py::ExecutionCandidateHandoff` | `handoff-api.ts::MarketToExecutionHandoff` |
| Execution→Cost | v1 | `platform_data/contracts/handoff_contracts.py::ExecutionPostTradeHandoff` | `handoff-api.ts::PostTradeHandoff` |
| Cost→Execution | v1 | `platform_data/contracts/handoff_contracts.py::BrokerStrategyRecommendation` | `handoff-api.ts::BrokerRecommendation` |

> 4 个类均由 `platform_data/adapters/handoff.py` 间接 re-export；详见 [ADR-0013](spec/adr/0013-platform-data-adapter-current-state.md)（`platform_data/adapters.py` → `adapters/` 子包 + `contracts/` 子包拆分）。

## Contract 1: HandoffMetadata

Shared envelope for all cross-module communication.

| Field | TypeScript | Python | Required |
|---|---|---|---|
| contract_version | `string` | `str` | Yes |
| source | `string` | `str` | Yes |
| handoff_target | `string` | `str` | Yes |
| generated_at | `string` | `str` (ISO 8601) | Yes |
| trace_id | `string` | `str` | Yes |
| origin_trace_id | `string \| null` | `str \| None` | No |

## Contract 2: MarketView → ExecutionView (MarketCandidate)

**API**: `POST /api/marketview/handoff/execution` → `GET /api/executions/handoff/candidates`

| Field | TypeScript | Python | Notes |
|---|---|---|---|
| metadata | `HandoffMetadata` | `HandoffMetadata` | |
| trade_date | `string \| null` | `str \| None` | YYYYMMDD format |
| pool_id | `string` | `str` | |
| pool_label | `string \| null` | `str \| None` | |
| candidate_payload | `CandidatePayload` | `MarketCandidatePayload` | |
| execution_hint | `Record<string,unknown>` | `dict[str,Any]` | |

### CandidatePayload nested structure

| Field | TypeScript | Python |
|---|---|---|
| source | `string` | `str` |
| handoff_target | `string` | `str` |
| trade_date | `string \| null` | `str \| None` |
| pool_id | `string` | `str` |
| pool_label | `string \| null` | `str \| None` |
| row_count | `number` | `int` |
| candidates | `CandidateRow[]` | `list[MarketCandidateRow]` |

## Contract 3: ExecutionView → CostView (PostTrade)

**API**: `POST /api/executions/handoff/post-trade`

| Field | TypeScript | Python | Notes |
|---|---|---|---|
| metadata | `HandoffMetadata` | `HandoffMetadata` | |
| order_id | `string` | `str` | |
| parent_execution_id | `string \| null` | `str \| None` | |
| broker | `string \| null` | `str \| None` | |
| strategy | `string \| null` | `str \| None` | |
| asset_class | `string \| null` | `str \| None` | |
| urgency | `string \| null` | `str \| None` | |
| route_ids | `string[]` | `list[str]` | |
| strategy_params | `Record<string,unknown>` | `dict[str,Any]` | |
| candidate_trace_id | `string \| null` | `str \| None` | back-pointer |

## Contract 4: CostView → ExecutionView (BrokerRecommendation)

**API**: `POST /api/tca/recommendations/pin` → `GET /api/broker-recommendations`

| Field | TypeScript | Python | Notes |
|---|---|---|---|
| metadata | `HandoffMetadata` | `HandoffMetadata` | |
| cohort | `string` | `str` | e.g. "broker_strategy" |
| asset_class | `string \| null` | `str \| None` | |
| broker | `string \| null` | `str \| None` | |
| strategy | `string \| null` | `str \| None` | |
| urgency | `string \| null` | `str \| None` | |
| sample_size | `number` | `int` | |
| arrival_bps | `number \| null` | `float \| None` | |
| implementation_bps | `number \| null` | `float \| None` | |
| severity | `string` | `str` | "normal" \| "warning" \| "critical" |
| rationale | `string` | `str` | |
| source_report_trace_id | `string \| null` | `str \| None` | |

## Type Mapping Rules

1. Python `int` → TypeScript `number`
2. Python `float` → TypeScript `number`
3. Python `str` → TypeScript `string`
4. Python `bool` → TypeScript `boolean`
5. Python `Optional[X]` → TypeScript `X | null`
6. Python `list[X]` → TypeScript `X[]`
7. Python `dict[str, Any]` → TypeScript `Record<string, unknown>`
8. Python `dict[str, X]` → TypeScript `Record<string, X>`
9. Dates are ISO 8601 strings on the wire (no `Date` objects)
10. Enums are lowercase strings on the wire

## Migration Path

When changing a contract field:
1. Add the new field as optional on both sides
2. Update this document
3. Deploy backend with dual-write (old + new format)
4. Deploy frontend reading new field, falling back to old
5. After all consumers migrated, remove old field
6. Bump contract version

## TODO: OpenAPI Code Generation

Currently both sides maintain independent types. Future improvements:
- Add FastAPI `response_model` OpenAPI generation
- Use `openapi-typescript` to generate TypeScript from OpenAPI spec
- CI/CD check to prevent drift between the two sides

## 运行时语义（handoff 容量 / TTL / 一致性）

### 3.1 Handoff 交换器（`platform_data/adapters/`）

```
MarketView ──mv-to-ev──▶ ExecutionView ◀──cv-to-ev (recommendations)── CostView
                              │  ▲
                              └──ev-to-cv──▶ CostView (post-trade peek)
```

| 通道 | 方向 | 写入端点 | 读取端点 | 容量/时序语义 |
|------|------|----------|----------|----------------|
| Market → Execution | 单槽（仅保留最新一份） | `POST /api/marketview/handoff/execution`（`MarketView/routers/marketview.py`） | ExecutionView 经 handoff API 读取 | 新写入覆盖旧值；无历史 |
| Execution → Cost | 按 order_id 映射 | ExecutionView 成交后写入 | `GET /api/tca/handoff/post-trade/{order_id}`（`CostView/api/routers/costview.py`） | 上限 500 条，TTL 7 天惰性清理，超限淘汰最旧 |
| Cost → Execution（recommendations） | 追加列表 | `POST /api/tca/recommendations/pin`（`costview.py`） | `GET /api/broker-recommendations`（`backend/api/routers/broker.py`） | 上限 200 条，追加 + 截断，**last-write-wins** |

**时序与一致性保证（重要）**：
- **同步性**：写入是请求内同步操作；读取是消费方在自身请求内**同步拉取**（无推送订阅）。前端经 `useHandoffContracts()` hook + `frontend/src/shared/services/handoff-api.ts` 按需读取。
- **可能读到过期数据**：内存后端条目 TTL 7 天，TTL 内的旧 recommendation 不会被自动失效——ExecutionView 读到的是"最近一次 pin 的结论"，不保证反映 CostView 最新分析。
- **冲突解决**：无合并逻辑，一律 last-write-wins；并发 pin 以后到达者为准。
- **无跨模块事务**：handoff 写入与业务写库是两个独立操作，无原子性保证。
- **Redis 后端**：3 个 key（`mv-to-ev` / `ev-to-cv` / `cv-to-ev`），`cv-to-ev` 列表上限 200（`rpush`+`ltrim`）；三通道均设 7 天 TTL（`pipeline` 内原子写入）。
- **载荷限制**：`strategy_params` ≤ 64 KB，超限返回 422。

契约定义：本文件 Contract 1–4（含 MarketView→ExecutionView、ExecutionView→CostView、CostView→ExecutionView recommendation 的完整字段）。

### 3.2 ETL 触发链（跨仓库，CostView 是只读消费者）

```
前端/脚本 ──POST /api/tca/runner/run (JWT 鉴权)──▶ backend :3000 ──代理──▶ EMSXDataPipeline Runner :8100 POST /run
                  GET /api/tca/runner/status ──────────────────────────▶ GET /status
```

- **职责归属**：数据更新（ETL 写入）唯一写入方是独立仓库 EMSXDataPipeline；CostView 自身**没有任何写库路径**（`data_access` 全部 `mode=ro`）。
- **入口**：`backend/api/routers/costview.py`（JWT 鉴权代理，前端统一经 `:3000`，不直连 Runner）；Runner 地址由 `EMSXVIEW_RUNNER_URL` 配置。
- **失败处理**：Runner 不可达 → `ApiResponse(success=False, "Runner unreachable: ...")`；Runner 返回非 2xx / 非 JSON → 失败响应。代理不会重试。
- **幂等性**：Runner 为**单任务模型**——已在运行时再次触发返回 HTTP 409，代理转而返回当前 `GET /status` 结果 + `"pipeline already running"`，不会并发重复执行。

---

## 运行时语义（handoff 容量 / TTL / 一致性）

### 3.1 Handoff 交换器（`platform_data/adapters/`）

```
MarketView ──mv-to-ev──▶ ExecutionView ◀──cv-to-ev (recommendations)── CostView
                              │  ▲
                              └──ev-to-cv──▶ CostView (post-trade peek)
```

| 通道 | 方向 | 写入端点 | 读取端点 | 容量/时序语义 |
|------|------|----------|----------|----------------|
| Market → Execution | 单槽（仅保留最新一份） | `POST /api/marketview/handoff/execution`（`MarketView/routers/marketview.py`） | ExecutionView 经 handoff API 读取 | 新写入覆盖旧值；无历史 |
| Execution → Cost | 按 order_id 映射 | ExecutionView 成交后写入 | `GET /api/tca/handoff/post-trade/{order_id}`（`CostView/api/routers/costview.py`） | 上限 500 条，TTL 7 天惰性清理，超限淘汰最旧 |
| Cost → Execution（recommendations） | 追加列表 | `POST /api/tca/recommendations/pin`（`costview.py`） | `GET /api/broker-recommendations`（`backend/api/routers/broker.py`） | 上限 200 条，追加 + 截断，**last-write-wins** |

**时序与一致性保证（重要）**：
- **同步性**：写入是请求内同步操作；读取是消费方在自身请求内**同步拉取**（无推送订阅）。前端经 `useHandoffContracts()` hook + `frontend/src/shared/services/handoff-api.ts` 按需读取。
- **可能读到过期数据**：内存后端条目 TTL 7 天，TTL 内的旧 recommendation 不会被自动失效——ExecutionView 读到的是"最近一次 pin 的结论"，不保证反映 CostView 最新分析。
- **冲突解决**：无合并逻辑，一律 last-write-wins；并发 pin 以后到达者为准。
- **无跨模块事务**：handoff 写入与业务写库是两个独立操作，无原子性保证。
- **Redis 后端**：3 个 key（`mv-to-ev` / `ev-to-cv` / `cv-to-ev`），`cv-to-ev` 列表上限 200（`rpush`+`ltrim`）；三通道均设 7 天 TTL（`pipeline` 内原子写入）。
- **载荷限制**：`strategy_params` ≤ 64 KB，超限返回 422。

契约定义：本文件 Contract 1–4（含 MarketView→ExecutionView、ExecutionView→CostView、CostView→ExecutionView recommendation 的完整字段）。

### 3.2 ETL 触发链（跨仓库，CostView 是只读消费者）

```
前端/脚本 ──POST /api/tca/runner/run (JWT 鉴权)──▶ backend :3000 ──代理──▶ EMSXDataPipeline Runner :8100 POST /run
                  GET /api/tca/runner/status ──────────────────────────▶ GET /status
```

- **职责归属**：数据更新（ETL 写入）唯一写入方是独立仓库 EMSXDataPipeline；CostView 自身**没有任何写库路径**（`data_access` 全部 `mode=ro`）。
- **入口**：`backend/api/routers/costview.py`（JWT 鉴权代理，前端统一经 `:3000`，不直连 Runner）；Runner 地址由 `EMSXVIEW_RUNNER_URL` 配置。
- **失败处理**：Runner 不可达 → `ApiResponse(success=False, "Runner unreachable: ...")`；Runner 返回非 2xx / 非 JSON → 失败响应。代理不会重试。
- **幂等性**：Runner 为**单任务模型**——已在运行时再次触发返回 HTTP 409，代理转而返回当前 `GET /status` 结果 + `"pipeline already running"`，不会并发重复执行。

---
