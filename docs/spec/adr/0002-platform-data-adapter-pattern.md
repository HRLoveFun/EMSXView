# ADR-0002: platform_data 适配器模式

> 状态: Accepted
> 日期: 2026-06-03
> 标签: architecture, integration

## 背景 (Context)

历史实现中 ExecutionView 与 CostView 通过深层 import 直接耦合：
- `backend/api/routers/*` 直接 import `CostView.src.db.*`
- `platform_data.adapters` 直接 import `CostView.src.raw_bdib_db.RawBDIBDB`

导致：
- CostView 内部重构时，ExecutionView 同步崩溃
- CostView 单元测试难以独立运行
- 跨域循环依赖风险

## 决策 (Decision)

建立 `platform_data/` 作为**唯一合法跨域访问入口**：

1. **当前实现 (2026-06-03)**：没有统一 `PlatformDataAccess` / `build_platform_data_access()` 入口；`platform_data.adapters` 已拆分为子包 (`handoff`, `market`, `redis_handoff`, `tca_bridge`)，每个子模块导出具体适配器类或工厂函数
2. **跨域符号直接 import**：从 `platform_data` 或 `platform_data.adapters` 直接导入公开符号
3. **公开/私有分界**：每个 Adapter 类**显式区分**外部可见方法与内部私有方法（`_` 前缀）
4. **跨域访问顺序**：
   - 优先走 `platform_data.<Symbol>` 公开 API
   - 其次走文档化的服务边界
   - **禁止**直接 `from CostView.src.* import ...` 跨域
   - **禁止**跨域调用 `_` 前缀方法

## 后果 (Consequences)

### 正面
- CostView 内部重构不影响 ExecutionView
- Adapter 单测可独立 mock
- 适配器粒度边界清晰（通过 `_` 前缀约定）

### 负面 / 取舍
- 新增跨域功能需先加 Adapter 方法
- Adapter 与具体实现一对一绑定，可能存在胶水代码
- 当前实现没有统一 `PlatformDataAccess` 入口，跨域调用方需直接 `import` 各子模块符号，命名一致性需纪律维护

## 备选方案 (Considered Alternatives)

- 方案 A: 通过事件总线解耦
  - 否决原因: 同步查询场景（TCA、regime）不适合事件驱动
- 方案 B: 暴露 CostView 公共 API（Facade）
  - 否决原因: 与"重构聚焦评估"目标冲突（ADR-0004）
- 方案 C: 合并到一个 monorepo Python 包
  - 否决原因: 部署模式复杂，单进程/微服务双模要求独立可部署

## 相关 ADR

- 引用: [ADR-0001](0001-one-logical-data-domain.md)
- 被引用: [ADR-0003](0003-executionview-owns-operational-state.md), [ADR-0004](0004-costview-focused-on-evaluation.md), [ADR-0007](0007-handoff-exchange-pattern.md)

## 实施注意事项

- 配套规范: `docs/spec/data-domain.md` 适配器清单
- 配套规范: `.codebuddy/rules/module-boundary.md` §2.2 公开/私有分界表
- 配套测试: `tests/boundaries/test_cross_module_imports.py` 检测 deep import
