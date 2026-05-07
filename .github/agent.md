# Agent 编码范式 — EMSX Trading Platform

> **接口**: VS Code Copilot Agent Mode
> **模型**: DeepSeek V4 Pro (DSN V4 Pro)
> **语言**: 简体中文（代码、变量名、文件路径、命令等技术内容除外）
> **版本**: 3.0 | 2026-05-07
> **状态**: 🔄 重构过渡期 — 以架构原则为准，具体路径随重构同步更新

---

## 0. 项目结构速览

当前项目是一个"一个前端壳 + 三个业务模块 + 一个逻辑数据域"的模块化架构：

| 位置 | 角色 |
|---|---|
| ExecutionView/frontend/src/App.tsx | 唯一浏览器入口 |
| ExecutionView/backend/api/main.py | 后端装配入口 |
| CostView/src/ | 盘后分析与管线 |
| platform_data/ | 共享数据适配层 |
| **文档入口** | **docs/index.md** |

详见 docs/spec/project-structure.md（结构）、docs/spec/data-domain.md（数据边界）、docs/spec/memory.md（架构记忆）。

---

## I. 四大支柱原则

### 支柱 1：架构优先
- 明确功能归属（交易执行 / 盘后分析 / 盘前分析）
- 遵守分层：路由层→服务层→仓储层→模型层（后端）；展示层→状态层→API层（前端）
- 上层可依赖下层，严禁反向依赖
- 跨域数据访问优先走 platform_data/ 共享适配层
- 优先复用已有抽象而非新建

### 支柱 2：意图驱动
- 每项任务以「需求→验收标准→设计→实现」链条推进
- 遇到模糊需求必须用 ⚠️ 主动澄清
- 计划文件（plan.md）经人工确认后写代码

### 支柱 3：闭环校验
- 所有输出通过 Lint → Test → Coverage → 接口 smoke test
- 后端改后重启；前端改后 
pm run build
- Bloomberg 字段变更校验：订阅列表→模型→解析器→前端类型→UI

### 支柱 4：决策留痕
- 架构决策写入 .github/knowledge/architecture-decisions.md
- 错误修复写入 .github/knowledge/error-patterns.md
- 迭代记录写入 .github/knowledge/iteration-log.md

---

## II. 绝对禁止

1. 禁止在未搜索已有抽象的情况下新建模块
2. 禁止功能重写代替增量重构
3. 禁止为满足一次性需求修改共享基础库
4. 禁止引入新依赖不经声明和批准
5. 禁止在未理解故障影响的情况下跳过校验
6. 禁止以 docs/archive/ 或 CostView/frontend/ 等遗留路径作为正式入口
7. 禁止直接操作 main 分支

---

## III. 七阶段工作流（强制）

PLAN → BUILD → DIFF → QA → APPROVAL → APPLY → DOCS

| 阶段 | Agent 行为 | 人工职责 |
|---|---|---|
| **PLAN** | 输出实施计划，标注受影响文件 | 确认/拒绝 |
| **BUILD** | 最小化实现，写测试 | 无 |
| **DIFF** | 输出 diff，说明变更理由 | 审查范围 |
| **QA** | lint → pytest → npm run build → smoke test | 查看报告 |
| **APPROVAL** | 等待显式批准 | **显式批准** |
| **APPLY** | 合并变更，重启后端（如需要） | 无 |
| **DOCS** | 更新迭代日志与知识库 | 审核 |

Agent **不得跳过任何阶段**。APPROVAL 仅在接受 "approved" / "looks good" / "LGTM" 后进入 APPLY。

---

## IV. 架构守护规则

### 输入防护栏
- 单次任务不超过 3 个关联文件变更
- 涉及 Bloomberg EMSX 字段时，计划必须列出所有需协同修改的文件

### 过程防护栏
- 所有变更在 git 分支进行
- 后端代码变更后必须重启后端
- 测试不得降低覆盖率

### 输出防护栏
- QA 阶段自动运行 lint、测试、构建
- Bloomberg 字段变更需额外验证一致性

---

## V. 技术债预算

| 类型 | 监控方式 |
|---|---|
| 代码膨胀 | 后端 ≤ 500 行/文件，前端 ≤ 300 行/文件 |
| 架构漂移 | 定期检查依赖方向，跨域直接导入标记违规 |
| 重复代码 | 同一模式 3+ 处 → 提取共享抽象 |
| 注释污染 | 移除"做了什么"的注释，保留"为什么" |

---

## VI. 项目编码契约

### 通用
- 提交格式：{type}: {description} – iteration #{n}（类型: fix/feat/refactor/docs/chore/perf）
- 日志默认 WARNING 等级

### 后端（Python / FastAPI）
- snake_case 命名；路由层只做参数验证和响应格式化；数据库查询通过 epositories/

### 前端（React / TypeScript）
- camelCase 变量/函数，PascalCase 组件/接口；API 封装在 services/ 层

### 数据域
- 日期格式新表统一 TEXT 'YYYY-MM-DD'
- SQLite 三件套：journal_mode=WAL; foreign_keys=ON; user_version=N

---

## VII. 知识库

| 文件 | 用途 |
|---|---|
| .github/knowledge/architecture-decisions.md | 架构决策历史 |
| .github/knowledge/error-patterns.md | 错误签名与已验证修复 |
| .github/knowledge/user-needs.md | 高频用户需求与自动化状态 |
| .github/knowledge/iteration-log.md | 全部迭代的审计轨迹 |
| .github/knowledge/metrics.md | 自评估指标与机制健康 |

---

## VIII. 任务后检查清单

1. 解决了一个错误？→ 检查/更新 error-patterns.md
2. 完成了一个需求？→ 检查/更新 user-needs.md
3. 涉及结构变更？→ 检查/更新 rchitecture-decisions.md
4. **必须追加**条目到 iteration-log.md
5. 变更影响现有文档？→ 同步更新对应文档

---

## IX. 回滚规则

如果变更导致测试失败或系统不稳定：
1. **立即回滚**到上一个可工作状态
2. 在 iteration-log.md 中记录失败（含诊断数据）
3. 在 error-patterns.md 中记录失败方案
4. 提出替代方案并说明理由
