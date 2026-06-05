# ADR-0013: platform_data 适配器现状与 data-domain.md 偏差

> 状态: Accepted
> 日期: 2026-06-03
> 标签: refactoring, data, documentation

## 背景 (Context)

`docs/spec/data-domain.md` v3.2 (2026-05-07) 中描述了 7 个适配器与统一入口：

| 描述中存在的 | 实际代码状态 |
|---|---|
| `ExecutionOperationalDataAdapter` | ❌ 不存在 |
| `CostViewAnalyticsAdapter` | ❌ 不存在 |
| `CostViewDatabaseAdapter` | ❌ 不存在 |
| `ExecutionHistoryAdapter` | ❌ 不存在 |
| `DataPlatformIngestionAdapter` | ❌ 不存在 |
| `HandoffExchangeAdapter` | ✅ 存在（`platform_data/adapters/handoff.py`） |
| `MarketReferenceDataAdapter` | ✅ 存在（`platform_data/adapters/market.py`） |
| `PlatformDataAccess` / `build_platform_data_access()` | ❌ 不存在 |

实际 `platform_data/` 提供的跨域符号：
- 类：`HandoffExchangeAdapter`, `RedisHandoffExchangeAdapter`, `MarketReferenceDataAdapter`
- 函数：`get_shared_handoff_exchange()`, `get_tca_query_service()`, `register_tca_service_impl()`

代码已完成 `platform_data/adapters.py` → `platform_data/adapters/` 子包拆分（`__init__.py` 维护向后兼容 re-export）。

data-domain.md 与实际代码存在显著偏差，已误导 AI agent 与新成员对架构的认知。

## 决策 (Decision)

1. **以代码为准**：所有新规范文档（`module-boundary.md` §2.3、`module-api-contracts.md`、`module-onboarding.md` §B）按**实际代码**列适配器
2. **更新 data-domain.md**：从 v3.2 → v3.3，反映实际适配器状态
3. **重写 ADR-0002**：修正"统一入口"为"按符号直接 import"
4. **未来补齐**：
   - `get_tca_query_service` 内部走 `register_tca_service_impl` 注入（已实现）
   - Operational/Analytics/Database/History/Ingestion 等适配器按需新建，走 [module-onboarding.md §B](../module-onboarding.md) 流程
   - 命名一致性：未来新适配器采用 `<Domain>Adapter` 类名 / `<verb>_<domain>` 工厂函数命名

## 后果 (Consequences)

### 正面
- 规范与代码一致，避免 AI agent 引用不存在符号
- 明确的"补齐路径"——后续按 module-onboarding.md §B 流程新增

### 负面 / 取舍
- 短期：data-domain.md 中"理想态"描述需降级为"待实现"
- 命名一致性靠纪律维护（缺统一入口做收敛）

## 备选方案 (Considered Alternatives)

- 方案 A: 不修 data-domain.md，按描述持续推进
  - 否决原因: 文档误导大于文档缺失
- 方案 B: 全删 data-domain.md
  - 否决原因: 文档仍有"原则"和"子域划分"价值，仅适配器清单需修
- 方案 C: 立即实现所有缺失适配器
  - 否决原因: 暂无强驱动力；按 YAGNI 原则按需新建

## 相关 ADR

- 引用: [ADR-0002](0002-platform-data-adapter-pattern.md)
- 修正: [ADR-0002](0002-platform-data-adapter-pattern.md)（统一入口 → 按符号直接 import）

## 实施注意事项

- 配套修正文件: `.codebuddy/rules/module-boundary.md` §2.3、`docs/spec/module-api-contracts.md`、`docs/spec/module-onboarding.md` §B
- 配套更新文件: `docs/spec/data-domain.md`（v3.2 → v3.3）
- 配套测试: `tests/boundaries/test_cross_module_imports.py`（仅检测 deep import，不依赖具体类名）
