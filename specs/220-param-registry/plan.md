# 220 — 券商参数字段注册表与前端迁移（DL-16 收尾 / DL-25 第二排）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-16**、**DL-25**
> 分支：`220-param-registry`（worktree `../EMSXView-wt-220-param-registry`，基于 `origin/main`）
> 依赖：DL-16（070 已交付策略注册表）；DL-25 第一批（219）已合并
> 说明：070 只落地了**策略参数 schema**；DL-16 要求的「规范字段 → 券商 × 策略字段名、类型与格式 + 只读 API」仍未实现，前端仍保留两份静态映射。本 PR 补齐注册表并删除映射。

---

## 1. 问题

1. **DL-16 规范未闭环**：`strategy_registry.py` 只有策略清单与参数 schema，没有券商字段名映射；而 DL-18/25 生成/预填参数必须知道每个券商策略的 EMSX 字段名。
2. **两份前端映射是唯一真相源**：
   - `broker-time-mapping.ts`：21 个券商的起止时间字段 + `EQ-MACQ/CLOSEPLUS` 覆盖；
   - `broker-volume-cap-mapping.ts`：18 个券商 × 策略的 volume cap 字段名 + 倍数 18；
   - 另有 `use-batch-route-state.ts` 内嵌的 `INTEGER_CAP_BROKERS`（CITI/JPM/UBS/SEB）。
   前端无法被后端决策引擎复用，且改一处要改两端。
3. **格式规则分散**：HH:MM → HHMM 整数、时间格式校验只在前端。

---

## 2. 方案

### S1 · 后端注册表契约（纯数据 + 纯函数）

新增 `platform_data/contracts/broker_param_fields.py`：

- `BROKER_PARAM_FIELDS_VERSION = "broker-param-fields-v1"`；
- `BROKER_TIME_FIELDS` / `BROKER_TIME_FIELD_OVERRIDES` / `BROKER_VOLUME_CAP_FIELDS`：与两份前端映射**逐项一致**；
- `VOLUME_CAP_MULTIPLIER = 18`；`INTEGER_CAP_BROKERS`（整数型上限券商）；
- `time_fields_for(broker, strategy)`：先查券商×策略覆盖，再查券商默认；
- `volume_cap_field_for(broker, strategy)`：大小写/非字母数字归一后匹配，回落 `*`；
- `is_integer_cap_broker(broker)`；
- `hhmm_to_emsx_int(value)` / `is_valid_hhmmss(value)`：格式规则单一真相源；
- `broker_param_fields_payload()`：JSON 可序列化快照（版本 + 三张表 + 倍数 + 整数券商 + 格式规则）。

**理论依据**：规范字段 → 券商字段名的转换只能有一处可写；引擎、预填、审计共用同一份注册表。

### S2 · 只读 API

`GET /api/broker-param-fields`（`routers/broker.py`，`verify_token`）：

```json
{
  "version": "broker-param-fields-v1",
  "timeFields": {"EQ-BARCLAY": {"start": "StartTime", "end": "EndTime"}},
  "timeFieldOverrides": {"EQ-MACQ": {"CLOSEPLUS": {"start": "ContStrtTime", "end": "ContEndTime"}}},
  "volumeCapFields": {"EQ-BARCLAY": {"AuctionEU": "Max Vol %"}},
  "volumeCapMultiplier": 18,
  "integerCapBrokers": ["EQ-CITI", "EQ-JPM", "EQ-UBS", "EQ-SEB"],
  "timeFormat": "HH:MM:SS",
  "hhmmIntRule": "HH*100+MM"
}
```

### S3 · 前端迁移

- 新增 `ExecutionView/module/hooks/use-broker-param-fields.ts`：模块级 promise 缓存 + `useBrokerParamFields()`；失败返回 `registry=null` 与错误信息。
- `use-batch-route-state.ts`：
  - 时间字段、volume cap 字段、整数券商、倍数全部改读 registry；
  - registry 未就绪时 `applyTimeToAll` 明确报错、`runValidation` 跳过自动 cap 并提示（**不静默写错字段**）；
  - `isValidTimeFormat` 改为调用 `broker-common-params.ts` 中的纯函数（不移除该文件）。
- `volume-cap-mapping-editor.tsx`：基础表改读 registry；localStorage 覆盖键改为引用同一常量。
- **顺带修复**：`volumeCapFieldFor` 现在真正读取 localStorage 覆盖（迁移前编辑器保存的覆盖从未进入自动填充路径）；覆盖优先于注册表，键格式不变。
- **删除** `ExecutionView/module/data/broker-time-mapping.ts` 与 `broker-volume-cap-mapping.ts`。
- `use-batch-route-state.test.tsx` 增加 registry mock，保证既有用例不触网。

### S4 · 对账与测试

- 新增 `backend/api/tests/test_broker_param_fields.py`：
  - 逐项对账：三张表与旧前端映射的期望快照完全一致（覆盖全部 21 券商时间字段、18 券商 volume cap、MACQ 覆盖、HSBC 名称归一、`TARGETCLO` 空字段）；
  - 纯函数单测（覆盖优先级、归一匹配、未知值、HHMM 整数、时间格式）；
  - API 契约测试：200 + 版本 + 关键字段。
- 前端：`use-broker-param-fields` 解析/回落的纯函数测试（如测试环境可用）。

---

## 3. 范围锁

- `platform_data/contracts/broker_param_fields.py`（新增）
- `platform_data/contracts/__init__.py`（导出）
- `backend/api/routers/broker.py`（只读端点）
- `backend/api/tests/test_broker_param_fields.py`（新增）
- `ExecutionView/module/hooks/use-broker-param-fields.ts`（新增）
- `ExecutionView/module/data/broker-common-params.ts`（时间校验）
- `ExecutionView/module/components/batch-route-order/use-batch-route-state.ts`
- `ExecutionView/module/components/batch-route-order/volume-cap-mapping-editor.tsx`
- `ExecutionView/module/components/batch-route-order/use-batch-route-state.test.tsx`（mock）
- 删除：`ExecutionView/module/data/broker-time-mapping.ts`、`broker-volume-cap-mapping.ts`
- 文档：`docs/api-contracts.md`、`specs/057-execution-decision-loop/tasks.md`

**不做**：不改提交链路字段；不改 route_order 请求；不引入 EUR 9% 前端分配（保持与旧映射逐项一致，差异另记）；不做注册表编辑 API（只读）。

---

## 4. 验收（P4）

1. 注册表与旧前端两份映射逐项一致（测试内快照对账）。
2. API 契约测试通过；未认证请求被拒绝。
3. 前端不再 import 被删映射；tsc 通过；批量路由既有测试通过。
4. 后端 `pytest backend/api/tests -q`、`python scripts/doc_check.py` 全绿。

---

## 5. 风险

- **字段名写错 → 参数写到错误 EMSX 字段**：以旧映射为唯一输入逐项对账；迁移前不修改任何条目。
- **API 不可用**：时间/volume cap 自动填充显式报错并跳过，不静默写入；批量提交本身不受影响（参数仍由各券商字段组件产生）。
- **localStorage 覆盖**：编辑器基础表改为 registry 后，覆盖键格式不变，已有覆盖继续生效；registry 未加载时只显示覆盖项。
