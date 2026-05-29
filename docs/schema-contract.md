# Schema Contract — Frontend TypeScript ↔ Backend Python

This document defines the canonical data types that cross the HTTP/WS boundary
between the React frontend and FastAPI backend. Both sides maintain independent
type definitions that MUST stay in sync with this contract.

## Contract Versioning

Each contract has a version string (e.g. `v1`). Breaking changes require a
version bump and a migration period where both old and new formats are accepted.

| Contract | Version | Python Source | TypeScript Source |
|---|---|---|---|
| Handoff Metadata | v1 | `platform_data/adapters.py::HandoffMetadata` | `handoff-api.ts::HandoffMetadata` |
| Market→Execution | v1 | `platform_data/adapters.py::ExecutionCandidateHandoff` | `handoff-api.ts::MarketToExecutionHandoff` |
| Execution→Cost | v1 | `platform_data/adapters.py::ExecutionPostTradeHandoff` | `handoff-api.ts::PostTradeHandoff` |
| Cost→Execution | v1 | `platform_data/adapters.py::BrokerStrategyRecommendation` | `handoff-api.ts::BrokerRecommendation` |

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
