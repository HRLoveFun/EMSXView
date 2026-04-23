# Project Memory

> 当前有效的架构记忆、工作约束与稳定约定。

---

## 1. Architecture Overview

当前仓库的真实结构是：

- 一个正式前端壳：Execution/frontend
- 三个业务模块：MarketView、Execution、CostView
- 一个逻辑数据域入口：platform_data

关键入口：

- 前端壳：Execution/frontend/src/App.tsx
- 后端装配层：Execution/backend/api/main.py
- CostView 管线与分析：CostView/src/
- 共享适配层：platform_data/adapters.py

---

## 2. Stable Design Rules

### 前端

- Execution/frontend 是唯一正式 UI 入口。
- CostView 的正式 UI 位于 Execution/frontend/src/modules/costview/。
- CostView/frontend/ 是遗留原型面，不应再承接默认产品开发。
- MarketView 当前已有壳内入口和真实快照基线，但后续扩展已暂停。

### 后端

- Execution/backend/api/main.py 现在主要负责应用装配，不再是唯一业务逻辑文件。
- Bloomberg 逻辑核心在 services/bloomberg_adapter.py。
- Python 后端代码修改后需要重启后端才能生效。

### 数据域

- 一个逻辑数据域不等于一个物理数据库。
- Execution 拥有 operational state。
- CostView 拥有 analytical 和 pipeline 数据。
- 跨域访问优先通过 platform_data/ 适配层，而不是深层直接导入。

---

## 3. Runtime Patterns

### 数据持久化语义

- ENABLE_DB_PERSISTENCE=true 时，后端启动会执行数据库 bootstrap。
- ENABLE_DB_PERSISTENCE=false 时，数据库被视为可选能力。
- 在可选模式下，/api/health 应返回 database.status=disabled，而不是 disconnected。

### Bloomberg 会话模式

- 订阅、请求响应、市场数据/RefData 已分离，避免 nextEvent 竞争。
- RefData pending 必须与对应 correlation id 精确绑定，不能全局粗暴清零。

### FX 汇率处理

- direct 与 inverse 同时存在时，inverse 更可靠。
- 已知 10x/100x/1000x 缩放报价应视为报价约定，而不是持续 WARNING。
- 只有缩放归一化后仍显著偏离的 direct/inverse 差异才保留 WARNING。

---

## 4. Module Status

### Execution

- 仍是当前最成熟的业务域。
- 订单、路由、认证、连接、实时等能力已模块化到 routers/services/repositories。

### CostView

- 是活跃分析域。
- TCA 查询、市场数据汇总、日更管线都以 CostView/src/ 为准。

### MarketView

- 第一批真实数据边界已落地：bdib_daily_summary 快照。
- 当前只保留只读基线，不继续扩功能，直到暂停解除。

---

## 5. Documentation Rules

- docs 根目录只保留仍然有效的运行指南、架构说明、数据边界、当前 handoff 和活跃计划文档。
- 已完成阶段总结、一次性诊断报告、旧架构路径说明，应移入 docs/archive/日期目录。
- 结构性决策写入 .github/knowledge/architecture-decisions.md。
- 运行时错误模式写入 .github/knowledge/error-patterns.md。

---

## 6. Operational Reminders

- Bloomberg 字段必须进入订阅列表才会收到。
- Bloomberg 字段类型必须与解析器类型一致。
- 默认日志级别为 WARNING，因此新增诊断日志要谨慎控制等级。
- MarketView、CostView、Execution 的共享数据接入优先从 platform_data 进入。
