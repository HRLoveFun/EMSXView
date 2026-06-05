# ADR 目录

> 架构决策记录（Architecture Decision Records）
> 每次新决策 = 一个 markdown 文件，永久保留
> 状态变迁: Proposed → Accepted → (Deprecated | Superseded by ADR-XXXX)

---

## 命名规范

```
NNNN-<kebab-case-title>.md
```

- 编号四位数字，全局递增，永不复用
- 标题使用英文 kebab-case，简洁可读
- 状态变化时**修改原文件状态行**，不创建新文件

---

## 编号分组（建议）

| 范围 | 主题 | 起始编号 |
|---|---|---|
| 0001-0099 | 总体架构（数据域、子域、模块职责） | 0001 |
| 0100-0199 | 跨模块集成（适配器、handoff、契约） | 0100 |
| 0200-0299 | 后端架构（router、service、repository） | 0200 |
| 0300-0399 | 前端架构（shell、模块、状态） | 0300 |
| 0400-0499 | 数据存储与管道 | 0400 |
| 0500-0599 | 外部集成（Bloomberg、Redis） | 0500 |
| 0600-0699 | 部署、运维、CI/CD | 0600 |
| 0700-0799 | 流程、文档、测试规范 | 0700 |
| 0800-0899 | 已被替代的历史决策（保留以供追溯） | 0800 |

---

## 维护规则

1. **新决策必须先建 Proposed ADR**，待评审通过后改状态为 Accepted
2. **不要删除已 Accepted 的 ADR**，即使决策被替代，标记为 Superseded 即可
3. **冲突检测**：写新 ADR 前 grep 现有 ADR 标题看是否重复
4. **同步规则**：代码实现与 ADR 出现偏差时，先改 ADR 再改代码（或明确记录偏差原因）
5. **AI Agent 必读**：进入仓库的 AI agent 应阅读所有 Accepted 状态的 ADR

---

## 当前 ADR 清单

### Accepted

| 编号 | 标题 | 标签 |
|---|---|---|
| [0001](0001-one-logical-data-domain.md) | 一个逻辑数据域，多种存储技术 | architecture, data |
| [0002](0002-platform-data-adapter-pattern.md) | platform_data 适配器模式 | architecture, integration |
| [0003](0003-executionview-owns-operational-state.md) | ExecutionView 拥有 operational state | data, backend, execution |
| [0004](0004-costview-focused-on-evaluation.md) | CostView 聚焦算法评估与分析 | data, costview, analytics |
| [0005](0005-data-pipeline-extraction.md) | Data Platform 子域从 CostView 抽取 | refactoring, data, architecture |
| [0006](0006-dataplatform-as-independent-subdomain.md) | Data Platform 作为独立子域 | architecture, data |
| [0007](0007-handoff-exchange-pattern.md) | Handoff 跨模块交换模式 | integration, frontend, backend |
| [0008](0008-frontend-module-registry-pattern.md) | 前端模块自注册模式 | frontend, architecture |
| [0009](0009-blend-of-microservice-and-monolith.md) | 单进程/微服务双模部署 | deployment, architecture |
| [0010](0010-bloomberg-session-model.md) | Bloomberg 会话模型 | external-integration, backend |
| [0011](0011-fx-rate-handling-rules.md) | FX 汇率处理规则 | data-processing, frontend |
| [0012](0012-config-isolation-rule.md) | 配置隔离 — DataPipeline/config 单一来源 | data, configuration, refactoring |
| [0013](0013-platform-data-adapter-current-state.md) | platform_data 适配器现状与 data-domain.md 偏差 | refactoring, data, documentation |

### Proposed
（暂无）

### Deprecated
（暂无）

### Superseded by
（暂无）
