# AGENTS.md — EMSX Trading Platform Agent Coding 范式

> **接口**: VS Code Copilot Agent Mode  
> **模型**: DeepSeek V4 Pro (DSN V4 Pro)  
> **语言**: 简体中文（代码、变量名、文件路径、命令等技术内容除外）  
> **版本**: 2.0 | 2026-05-04  
> **状态**: 🔄 重构过渡期 — 以架构原则为准，具体路径随重构同步更新

---

## I. 四大支柱原则

### 支柱 1：架构优先（Architecture-First）

在编写任何代码前，Agent 必须基于已有架构进行设计：
- 明确功能归属：属于哪个业务域（交易执行 / 盘后分析 / 盘前分析），边界在哪里
- 遵守分层架构：`路由层 → 服务层 → 仓储层 → 模型层`（后端）、`展示层 → 状态层 → API 层`（前端）
- 尊重模块依赖方向：上层可依赖下层，严禁反向依赖
- 跨域数据访问优先通过共享适配层，而非模块间深层直接导入
- 优先复用而非重写：先搜索项目已有抽象

### 支柱 2：意图驱动（Intent-Driven）

人是意图的来源，Agent 是实现者：
- 每项任务以「需求 → 验收标准 → 设计 → 实现」链条推进
- Agent 不猜测意图，遇到模糊需求必须用 ⚠️ 主动澄清
- 不确定时输出计划文件（plan.md），经人工确认后方可写代码

### 支柱 3：闭环校验（Closed-Loop Verification）

生成的不只是代码，而是「代码 + 自校验证据」：
- 所有输出必须通过：Lint → Test → Coverage → 接口 smoke test
- 后端代码修改后必须重启后端并验证
- 前端代码修改后必须 `npm run build` 通过
- Bloomberg 字段变更需校验：订阅列表 → 后端模型 → 解析器 → 前端类型 → UI 列

### 支柱 4：决策留痕（Auditable Decisions）

Agent 的每一步行动均被记录：
- 计划摘要、变更清单、匹配的架构规则、校验结果
- 架构决策写入 `.github/knowledge/architecture-decisions.md`
- 错误修复写入 `.github/knowledge/error-patterns.md`
- 迭代记录写入 `.github/knowledge/iteration-log.md`
- 工程领导者可在任意时间点审查历史决策链

---

## II. 项目架构卡

### 业务模块架构

项目采用 **「一个前端壳 + N 个业务模块 + 一个逻辑数据域」** 的模块化架构：

- **前端壳**：唯一浏览器入口，承载所有业务模块的 UI 表面
- **业务模块**：按业务领域拆分（如 Execution、CostView、MarketView），各模块可独立演进
- **逻辑数据域**：通过共享适配层统一跨域数据访问，模块内部可自选存储技术（PostgreSQL / SQLite / in-memory）

> ⚠️ **重构过渡期**：当前仓库结构正在大规模重构中。具体目录路径、模块名称以最新 `docs/PROJECT_STRUCTURE.md` 或已确认的 `plan.md` 为准。AGENTS.md 仅描述**永久性架构原则**，不绑定具体路径。

### 分层架构与依赖方向

无论是前端还是后端，每个业务模块内部遵循统一的分层契约：

```
┌── UI 层 ───────────────────────────────────────────────┐
│  页面 / 组件 / 视图                                      │
│       ↓  仅依赖                                         │
│  状态层 (hooks / stores)                               │
│       ↓  仅依赖                                         │
│  服务层 (API 调用封装)                                  │
│       ↓  仅依赖                                         │
│  传输层 (HTTP / WebSocket 客户端)                       │
└────────────────────────────────────────────────────────┘
                        ↓ HTTP/WS
┌── 后端层 ──────────────────────────────────────────────┐
│  路由层 (参数验证 + 响应格式化)                          │
│       ↓  仅依赖                                         │
│  服务层 (业务逻辑 + 外部适配器)                          │
│       ↓  仅依赖                                         │
│  仓储层 (持久化数据访问)                                │
│       ↓  仅依赖                                         │
│  模型层 (数据模型 + API 契约)                           │
└────────────────────────────────────────────────────────┘
                        ↓
┌── 数据域 ──────────────────────────────────────────────┐
│  共享适配层 (跨模块数据访问的唯一入口)                    │
│       ↓                                                │
│  各模块自有数据存储 (存储技术按工作负载选择)              │
└────────────────────────────────────────────────────────┘
```

**依赖铁律**：上层可依赖下层，严禁反向依赖。共享适配层是跨模块数据访问的唯一合法入口。

### 关键约束（永久性）

| 约束 | 说明 |
|---|---|
| 唯一前端入口 | 项目只有一个浏览器入口，所有 UI 模块在此壳内挂载 |
| 分层依赖方向 | 上层依赖下层，禁止反向（组件不可被 hooks 依赖，服务不可被路由调用） |
| 跨域数据访问 | **禁止**模块间直接深层导入；跨模块数据访问**必须**通过共享适配层 |
| 后端装配入口 | 后端入口文件负责应用启动、路由注册、生命周期管理；业务逻辑归入各层 |
| Bloomberg 字段管理 | 字段须在订阅列表中才能收到；字段类型须与解析器一致；修改字段须联动更新 订阅→模型→解析器→前端类型→UI |
| 遗留代码 | `CostView/frontend/`、`app/`、`config/` 为遗留占位，不作为活跃架构锚点 |

> ⚠️ **重构过渡期规则**：当 AGENTS.md 中的具体路径/模块名与已确认的重构计划（以 `plan.md` 或最新 `docs/PROJECT_STRUCTURE.md` 为准）冲突时，**以后者为准**。Agent 不得以「AGENTS.md 中写的是旧路径」为由拒绝修改涉及旧路径的代码。

---

## III. 绝对禁止

1. **禁止在未搜索项目已有抽象的情况下新建模块** — 先 `grep_search` / `semantic_search` 查找可复用代码
2. **禁止功能重写代替增量重构** — 每次重构必须保持系统可运行、测试全通过
3. **禁止为满足一次性需求修改共享基础库** — 如共享适配层、数据契约文件；修改前必须在 plan.md 中说明影响范围
4. **禁止引入新依赖不经声明和批准** — 新依赖必须在 plan.md 中说明理由并获批准
5. **禁止在未全面理解故障影响的情况下跳过任何校验步骤** — 特别是 Bloomberg 字段变更
6. **禁止将遗留原型目录当作正式入口** — 以 `docs/PROJECT_STRUCTURE.md` 中标注的正式入口为准
7. **禁止使用已废弃的目录名作为当前结构描述** — 以最新 `docs/PROJECT_STRUCTURE.md` 或 `plan.md` 为准
8. **禁止直接操作 main 分支** — 所有变更必须在 git 分支进行

---

## IV. 七阶段工作流状态机（强制）

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  PLAN    │  →│  BUILD   │  →│  DIFF    │  →│  QA      │  →│ APPROVAL │  →│  APPLY   │  →│  DOCS    │
│ 制定计划  │   │ 最小实现  │   │ 差异审核 │   │ 质量校验  │   │ 人工批准  │   │ 应用变更 │   │ 文档更新  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘   └──────────┘
```

| 阶段 | 触发条件 | Agent 行为 | 人工职责 |
|---|---|---|---|
| **PLAN** | 收到任务 | 输出实施计划，标注受影响文件与模块边界；参考 `.github/knowledge/architecture-decisions.md`；如涉及执行平台路线图，参考 `docs/EXECUTION_PLATFORM_WBS.md` | 确认/拒绝计划 |
| **BUILD** | 计划获批 | 在分支最小化实现，优先复用；遵循项目编码契约；写测试 | 无 |
| **DIFF** | 代码完成 | 输出统一 diff，说明变更理由与集成点 | 初步审查变更范围 |
| **QA** | Diff 提交 | 自动运行：lint → 后端 pytest → 前端 `npm run build` → 接口 smoke test；Bloomberg 字段变更额外校验订阅/模型/解析器一致性 | 查看质检报告 |
| **APPROVAL** | QA 通过 | 等待批准（仅接受 "approved" / "looks good" / "LGTM"） | **显式批准** |
| **APPLY** | 获得批准 | 将变更合并到目标分支，验证合并结果；重启后端（如涉及 Python 变更） | 无 |
| **DOCS** | 变更生效 | 更新 `.github/knowledge/iteration-log.md`；检查是否需要更新错误模式/用户需求/架构决策；如变更影响 `docs/MEMORY.md` 或 `docs/HANDOFF.md` 的表述，同步更新 | 查看文档是否完整 |

> **关键规则**：Agent 不得跳过任何阶段。APPROVAL 阶段仅在收到人类明确批准后方可进入 APPLY。

---

## V. 架构守护规则（多层防护栏）

### 第一层：输入防护栏（Input Guardrails）

- 单次任务不超过 3 个关联文件变更，超出需拆分为多个子任务
- 任务描述必须包含：目的、预期结果、约束条件
- Agent 必须首先输出 PLAN，不得跳过计划直接编码
- 涉及 Bloomberg EMSX 字段变更时，计划必须列出所有需协同修改的文件（订阅 → 模型 → 解析器 → 前端类型 → UI）

### 第二层：过程防护栏（Process Guardrails）

过程约束已在 `.github/instructions/` 下按作用域定义：

| 指令文件 | 适用场景 | 作用域 |
|---|---|---|
| `architecture.instructions.md` | 架构审查、结构变更、技术债评估、重构 | 后端入口文件、前端 `src/`、分析管线 `src/`（具体路径以 `docs/PROJECT_STRUCTURE.md` 为准） |
| `error-patterns.instructions.md` | 调试错误、分析测试失败、运行时异常 | `**/*.py`, `**/*.ts`, `**/*.tsx` |
| `task-planning.instructions.md` | 任务分解、实施计划、检查点定义 | 全局 |
| `user-needs.instructions.md` | 用户需求分析、功能规划、自动化评估 | 全局 |

核心过程规则：
- 所有变更必须在 git 分支进行
- 必须先输出计划文件，经人工确认后方可写代码
- 必须从已有抽象中搜索可复用代码
- 后端代码变更后必须重启后端
- 测试不得降低覆盖率

### 第三层：输出防护栏（Output Guardrails）

- QA 阶段自动运行 lint、测试、构建
- 检查清单：是否引入新依赖、是否正确实现错误处理、是否符合项目架构模式
- Bloomberg 字段变更需额外验证：字段在订阅列表 ✓、解析器类型匹配 ✓、前端接口镜像后端 ✓

---

## VI. 技术债预算

| 债务类型 | 监控方式 | 处理策略 |
|---|---|---|
| 代码膨胀 | 单文件不超过 500 行（后端）/ 300 行（前端）；超出标记 `remediate` | 拆分为独立模块 |
| 架构漂移 | 定期检查依赖方向，跨域直接导入标记违规 | 迁至共享适配层 |
| 重复代码 | 同一模式出现 3+ 处标记 | 提取为共享抽象 |
| 注释污染 | AI 生成的冗余注释扫描 | 移除仅描述"做了什么"的注释，保留"为什么这样做" |
| 遗留引用 | 定期扫描 `docs/PROJECT_STRUCTURE.md` 中标注的遗留/废弃路径 | 更新为新路径或移除 |

**健康度信号**：
- 代码健康时 → Agent 正常生成
- 模块超过 500 行或函数超过 50 行 → Agent 需标记 ⚠️ 并谨慎处理
- 无测试覆盖的业务逻辑模块 → Agent 必须先补测试再修改

---

## VII. 人机角色分工

| 角色 | 人 | Agent |
|---|---|---|
| 架构决策 | ✅ 裁决者 | ⚠️ 顾问（参考 `.github/knowledge/architecture-decisions.md`） |
| 产品管理 | ✅ 定义需求与优先级 | ❌ |
| 需求分析 | ✅ 验收标准最终拍板 | ⚠️ 辅助拆解 |
| 代码实现 | ✅ 审查确认 | ✅ 主力执行 |
| 测试编写 | ✅ 定义策略 | ✅ 生成测试 |
| 文档更新 | ✅ 审核 | ✅ 草稿 |
| 安全检查 | ✅ 审批例外 | ✅ 生成报告 |
| 部署决策 | ✅ 最终决策 | ❌ |
| Bloomberg 字段管理 | ✅ 确认字段需求 | ⚠️ 提醒订阅/类型一致性 |
| 知识库维护 | ✅ 审核 | ✅ 自动更新迭代日志、错误模式 |

---

## VIII. 项目编码契约

### 通用

- **语言**: 所有 AI 回复使用简体中文；代码、变量名、文件路径、命令使用英文
- **提交信息格式**: `{type}: {description} – iteration #{log_entry_number}`  
  类型: `fix` | `feat` | `refactor` | `docs` | `chore` | `perf`
- **文件大小**: 后端单文件 ≤ 500 行，前端单文件 ≤ 300 行，超出必须拆分
- **日志等级**: 默认 WARNING；诊断信息使用 WARNING+；避免 INFO/DEBUG 噪音

### 后端 (Python / FastAPI)

- 命名: `snake_case`（变量、函数、文件）；`PascalCase`（类）
- 路由文件只含参数验证和响应格式化 — 业务逻辑归入 `services/`
- 所有数据库查询必须通过 `repositories/`，禁止在 route/service 中 execute raw SQL
- 所有数据库 schema 变更必须通过迁移脚本，禁止 ad-hoc 表操作
- Bloomberg 字段：必须在订阅列表中才能收到；字段类型 (str/int/float) 必须与解析器一致
- 新 API 端点必须使用 `schemas.py` 中的 Pydantic 模型

### 前端 (React / TypeScript)

- 命名: `camelCase`（变量、函数）；`PascalCase`（组件、接口）
- 状态管理: React hooks + context（不使用 Redux/Zustand）
- API 调用封装在 `services/` 层
- TypeScript 接口必须与后端 Pydantic 模型保持镜像一致
- 模块拆分：按业务领域拆分，各模块内遵循「组件 → hooks → services → api」分层

### 数据域

- 日期格式: 新表统一 `TEXT 'YYYY-MM-DD'`（legacy YYYYMMDD 视为技术债）
- SQLite Pragma 三件套: `journal_mode=WAL; foreign_keys=ON; user_version=N`
- 索引仅按已知查询模式添加，不滥加
- 跨域访问优先顺序: `共享适配层` → 域服务边界 → 直接深层导入（需显式说明理由）

---

## IX. 知识库与技能体系

### 知识库（`.github/knowledge/`）

Agent 必须在开始任务前查阅相关知识库文件：

| 文件 | 用途 | 查阅时机 |
|---|---|---|
| `error-patterns.md` | 已知错误签名与已验证修复方案 | 调试任何错误前 |
| `user-needs.md` | 用户需求频率与自动化状态 | 收到新需求时 |
| `architecture-decisions.md` | 架构决策历史与审查计划 | 结构变更前 |
| `iteration-log.md` | 所有迭代的审计轨迹 | PLAN 阶段参考历史 |
| `metrics.md` | 自评估指标与机制健康 | 每两周自检 |

### 子代理技能（`.github/skills/`）

复杂任务可调用专用子代理：

| 技能 | 用途 |
|---|---|
| `architecture-reviewer` | 架构审查、技术债分析、重构规划 |
| `error-resolver` | 基于模式识别的错误修复 |
| `need-analyzer` | 用户需求分析与优先级排序 |
| `schema-designer` | SQLite/关系型 schema 设计与审查 |
| `self-assessor` | 迭代更新机制自评估 |
| `task-planner` | 任务分解与检查点规划 |

### 仓库记忆（`/memories/repo/`）

存储在仓库记忆中的专题知识点，Agent 可通过 `memory` 工具查阅。

---

## X. 任务后检查清单（每次任务完成后执行）

1. **错误模式**: 解决了一个错误？→ 检查 `error-patterns.md`，如为新模式且出现 2+ 次则录入
2. **用户需求**: 完成了一个需求？→ 检查 `user-needs.md`，如为重复模式则更新频率
3. **架构影响**: 变更涉及结构？→ 检查 `architecture-decisions.md`，新的架构选择需记录
4. **迭代日志**: 必须追加条目到 `iteration-log.md`（日期、类型、触发条件、动作、结果）
5. **文档同步**: 变更影响现有文档 → 同步更新 `docs/MEMORY.md`、`docs/HANDOFF.md` 等

---

## XI. 回滚规则

如果变更导致测试失败或系统不稳定：

1. **立即回滚**到上一个可工作状态
2. 在 `iteration-log.md` 中记录失败（含诊断数据）
3. 在 `error-patterns.md` 中记录失败方案以防止重试
4. 提出替代方案并说明理由

---

## XII. 维护与演进

| 机制 | 说明 |
|---|---|
| 规则反馈循环 | 发现 AI 违规时，将案例补充到本文的「绝对禁止」或 `.github/instructions/` |
| 定期审计 | 按季度审计 AI 生成代码健康度（代码膨胀、架构漂移、注释污染） |
| 模型评估 | 持续跟踪 DSN V4 Pro 在本项目上的表现 |
| 文档归档 | 一次性诊断报告、已完成阶段总结移入 `docs/archive/`，保持根目录精简 |

---

> **核心命题**: 将速度与安全从对立的两极转化为互补的伙伴。规则体系不是限制 AI 的能力，而是为其提供「正确驾驶的铺装道路」——让 AI 将创造力倾注于最合适的环节，同时确保系统整体的架构长期健康。






# Claude prompting guide

## General tips for effective prompting

### 1. Be clear and specific
   - Clearly state your task or question at the beginning of your message.
   - Provide context and details to help Claude understand your needs.
   - Break complex tasks into smaller, manageable steps.

   Bad prompt:
   <prompt>
   "Help me with a presentation."
   </prompt>

   Good prompt:
   <prompt>
   "I need help creating a 10-slide presentation for our quarterly sales meeting. The presentation should cover our Q2 sales performance, top-selling products, and sales targets for Q3. Please provide an outline with key points for each slide."
   </prompt>

   Why it's better: The good prompt provides specific details about the task, including the number of slides, the purpose of the presentation, and the key topics to be covered.

### 2. Use examples
   - Provide examples of the kind of output you're looking for.
   - If you want a specific format or style, show Claude an example.

   Bad prompt:
   <prompt>
   "Write a professional email."
   </prompt>

   Good prompt:
   <prompt>
   "I need to write a professional email to a client about a project delay. Here's a similar email I've sent before:

   'Dear [Client],
   I hope this email finds you well. I wanted to update you on the progress of [Project Name]. Unfortunately, we've encountered an unexpected issue that will delay our completion date by approximately two weeks. We're working diligently to resolve this and will keep you updated on our progress.
   Please let me know if you have any questions or concerns.
   Best regards,
   [Your Name]'

   Help me draft a new email following a similar tone and structure, but for our current situation where we're delayed by a month due to supply chain issues."
   </prompt>

   Why it's better: The good prompt provides a concrete example of the desired style and tone, giving Claude a clear reference point for the new email.

### 3. Encourage thinking
   - For complex tasks, ask Claude to "think step-by-step" or "explain your reasoning."
   - This can lead to more accurate and detailed responses.

   Bad prompt:
   <prompt>
   "How can I improve team productivity?"
   </prompt>

   Good prompt:
   <prompt>
   "I'm looking to improve my team's productivity. Think through this step-by-step, considering the following factors:
   1. Current productivity blockers (e.g., too many meetings, unclear priorities)
   2. Potential solutions (e.g., time management techniques, project management tools)
   3. Implementation challenges
   4. Methods to measure improvement

   For each step, please provide a brief explanation of your reasoning. Then summarize your ideas at the end."
   </prompt>

   Why it's better: The good prompt asks Claude to think through the problem systematically, providing a guided structure for the response and asking for explanations of the reasoning process. It also prompts Claude to create a summary at the end for easier reading.

### 4. Iterative refinement
   - If Claude's first response isn't quite right, ask for clarifications or modifications.
   - You can always say "That's close, but can you adjust X to be more like Y?"

   Bad prompt:
   <prompt>
   "Make it better."
   </prompt>

   Good prompt:
   <prompt>
   "That’s a good start, but please refine it further. Make the following adjustments:
   1. Make the tone more casual and friendly
   2. Add a specific example of how our product has helped a customer
   3. Shorten the second paragraph to focus more on the benefits rather than the features"
   </prompt>

   Why it's better: The good prompt provides specific feedback and clear instructions for improvements, allowing Claude to make targeted adjustments instead of just relying on Claude’s innate sense of what “better” might be — which is likely different from the user’s definition!

### 5. Leverage Claude's knowledge
   - Claude has broad knowledge across many fields. Don't hesitate to ask for explanations or background information
   - Be sure to include relevant context and details so that Claude’s response is maximally targeted to be helpful

   Bad prompt:
   <prompt>
   "What is marketing? How do I do it?"
   </prompt>

   Good prompt:
   <prompt>
   "I'm developing a marketing strategy for a new eco-friendly cleaning product line. Can you provide an overview of current trends in green marketing? Please include:
   1. Key messaging strategies that resonate with environmentally conscious consumers
   2. Effective channels for reaching this audience
   3. Examples of successful green marketing campaigns from the past year
   4. Potential pitfalls to avoid (e.g., greenwashing accusations)

   This information will help me shape our marketing approach."
   </prompt>

   Why it's better: The good prompt asks for specific, contextually relevant  information that leverages Claude's broad knowledge base. It provides context for how the information will be used, which helps Claude frame its answer in the most relevant way.

### 6. Use role-playing
   - Ask Claude to adopt a specific role or perspective when responding.

   Bad prompt:
   <prompt>
   "Help me prepare for a negotiation."
   </prompt>

   Good prompt:
   <prompt>
   "You are a fabric supplier for my backpack manufacturing company. I'm preparing for a negotiation with this supplier to reduce prices by 10%. As the supplier, please provide:
   1. Three potential objections to our request for a price reduction
   2. For each objection, suggest a counterargument from my perspective
   3. Two alternative proposals the supplier might offer instead of a straight price cut

   Then, switch roles and provide advice on how I, as the buyer, can best approach this negotiation to achieve our goal."
   </prompt>

   Why it's better: This prompt uses role-playing to explore multiple perspectives of the negotiation, providing a more comprehensive preparation. Role-playing also encourages Claude to more readily adopt the nuances of specific perspectives, increasing the intelligence and performance of Claude’s response.


## Task-specific tips and examples

### Content Creation

1. **Specify your audience**
   - Tell Claude who the content is for.

   Bad prompt:
   <prompt>
   "Write something about cybersecurity."
   </prompt>

   Good prompt:
   <prompt>
   "I need to write a blog post about cybersecurity best practices for small business owners. The audience is not very tech-savvy, so the content should be:
   1. Easy to understand, avoiding technical jargon where possible
   2. Practical, with actionable tips they can implement quickly
   3. Engaging and slightly humorous to keep their interest

   Please provide an outline for a 1000-word blog post that covers the top 5 cybersecurity practices these business owners should adopt."
   </prompt>

   Why it's better: The good prompt specifies the audience, desired tone, and key characteristics of the content, giving Claude clear guidelines for creating appropriate and effective output.

2. **Define the tone and style**
   - Describe the desired tone.
   - If you have a style guide, mention key points from it.

   Bad prompt:
   <prompt>
   "Write a product description."
   </prompt>

   Good prompt:
   <prompt>
   "Please help me write a product description for our new ergonomic office chair. Use a professional but engaging tone. Our brand voice is friendly, innovative, and health-conscious. The description should:
   1. Highlight the chair's key ergonomic features
   2. Explain how these features benefit the user's health and productivity
   3. Include a brief mention of the sustainable materials used
   4. End with a call-to-action encouraging readers to try the chair

   Aim for about 200 words."
   </prompt>

   Why it's better: This prompt provides clear guidance on the tone, style, and specific elements to include in the product description.

3. **Define output structure**
   - Provide a basic outline or list of points you want covered.

   Bad prompt:
   <prompt>
   "Create a presentation on our company results."
   </prompt>

   Good prompt:
   <prompt>
   "I need to create a presentation on our Q2 results. Structure this with the following sections:
   1. Overview
   2. Sales Performance
   3. Customer Acquisition
   4. Challenges
   5. Q3 Outlook

   For each section, suggest 3-4 key points to cover, based on typical business presentations. Also, recommend one type of data visualization (e.g., graph, chart) that would be effective for each section."
   </prompt>

   Why it's better: This prompt provides a clear structure and asks for specific elements (key points and data visualizations) for each section.

### Document summary and Q&A

1. **Be specific about what you want**
   - Ask for a summary of specific aspects or sections of the document.
   - Frame your questions clearly and directly.
   - Be sure to specify what kind of summary (output structure, content type) you want

2. **Use the document names**
   - Refer to attached documents by name.

3. **Ask for citations**
   - Request that Claude cites specific parts of the document in its answers.

Here is an example that combines all three of the above techniques:

   Bad prompt:
   <prompt>
   "Summarize this report for me."
   </prompt>

   Good prompt:
   <prompt>
   "I've attached a 50-page market research report called 'Tech Industry Trends 2023'. Can you provide a 2-paragraph summary focusing on AI and machine learning trends? Then, please answer these questions:
   1. What are the top 3 AI applications in business for this year?
   2. How is machine learning impacting job roles in the tech industry?
   3. What potential risks or challenges does the report mention regarding AI adoption?

   Please cite specific sections or page numbers when answering these questions."
   </prompt>

   Why it's better: This prompt specifies the exact focus of the summary, provides specific questions, and asks for citations, ensuring a more targeted and useful response. It also indicates the ideal summary output structure, such as limiting the response to 2 paragraphs.

### Data analysis and visualization

1. **Specify the desired format**
   - Clearly describe the format you want the data in.

   Bad prompt:
   <prompt>
   "Analyze our sales data."
   </prompt>

   Good prompt:
   <prompt>
   "I've attached a spreadsheet called 'Sales Data 2023'. Can you analyze this data and present the key findings in the following format:

   1. Executive Summary (2-3 sentences)

   2. Key Metrics:
      - Total sales for each quarter
      - Top-performing product category
      - Highest growth region

   3. Trends:
      - List 3 notable trends, each with a brief explanation

   4. Recommendations:
      - Provide 3 data-driven recommendations, each with a brief rationale

   After the analysis, suggest three types of data visualizations that would effectively communicate these findings."
   </prompt>

   Why it's better: This prompt provides a clear structure for the analysis, specifies key metrics to focus on, and asks for recommendations and visualization suggestions for further formatting.

### Brainstorming
 1. Use Claude to generate ideas by asking for a list of possibilities or alternatives.
     - Be specific about what topics you want Claude to cover in its brainstorming

   Bad prompt:
   <prompt>
   "Give me some team-building ideas."
   </prompt>

   Good prompt:
   <prompt>
   "We need to come up with team-building activities for our remote team of 20 people. Can you help me brainstorm by:
   1. Suggesting 10 virtual team-building activities that promote collaboration
   2. For each activity, briefly explain how it fosters teamwork
   3. Indicate which activities are best for:
      a) Ice-breakers
      b) Improving communication
      c) Problem-solving skills
   4. Suggest one low-cost option and one premium option."
   </prompt>

   Why it's better: This prompt provides specific parameters for the brainstorming session, including the number of ideas, type of activities, and additional categorization, resulting in a more structured and useful output.

2. Request responses in specific formats like bullet points, numbered lists, or tables for easier reading.

   Bad Prompt:
   <prompt>
   "Compare project management software options."
   </prompt>

   Good Prompt:
   <prompt>
   "We're considering three different project management software options: Asana, Trello, and Microsoft Project. Can you compare these in a table format using the following criteria:
   1. Key Features
   2. Ease of Use
   3. Scalability
   4. Pricing (include specific plans if possible)
   5. Integration capabilities
   6. Best suited for (e.g., small teams, enterprise, specific industries)"
   </prompt>

   Why it's better: This prompt requests a specific structure (table) for the comparison, provides clear criteria, making the information easy to understand and apply.

## Troubleshooting, minimizing hallucinations, and maximizing performance

1. **Allow Claude to acknowledge uncertainty**
   - Tell Claude that it should say it doesn’t know if it doesn’t know. Ex. “If you're unsure about something, it's okay to admit it. Just say you don’t know.”

2. **Break down complex tasks**
   - If a task seems too large and Claude is missing steps or not performing certain steps well, break it into smaller steps and work through them with Claude one message at a time.

3. **Include all contextual information for new requests**
   - Claude doesn't retain information from previous conversations, so include all necessary context in each new conversation.

## Example good vs. bad prompt examples

These are more examples that combine multiple prompting techniques to showcase the stark difference between ineffective and highly effective prompts.

### Example 1: Marketing strategy development

Bad prompt:
<prompt>
"Help me create a marketing strategy."
</prompt>

Good prompt:
<prompt>
"As a senior marketing consultant, I need your help developing a comprehensive marketing strategy for our new eco-friendly smartphone accessory line. Our target audience is environmentally conscious millennials and Gen Z consumers. Please provide a detailed strategy that includes:

1. Market Analysis:
   - Current trends in eco-friendly tech accessories
   - 2-3 key competitors and their strategies
   - Potential market size and growth projections

2. Target Audience Persona:
   - Detailed description of our ideal customer
   - Their pain points and how our products solve them

3. Marketing Mix:
   - Product: Key features to highlight
   - Price: Suggested pricing strategy with rationale
   - Place: Recommended distribution channels
   - Promotion: 
     a) 5 marketing channels to focus on, with pros and cons for each
     b) 3 creative campaign ideas for launch

4. Content Strategy:
   - 5 content themes that would resonate with our audience
   - Suggested content types (e.g., blog posts, videos, infographics)

5. KPIs and Measurement:
   - 5 key metrics to track
   - Suggested tools for measuring these metrics

Please present this information in a structured format with headings and bullet points. Where relevant, explain your reasoning or provide brief examples.

After outlining the strategy, please identify any potential challenges or risks we should be aware of, and suggest mitigation strategies for each."
</prompt>

Why it's better: This prompt combines multiple techniques including role assignment, specific task breakdown, structured output request, brainstorming (for campaign ideas and content themes), and asking for explanations. It provides clear guidelines while allowing room for Claude's analysis and creativity.

### Example 2: Financial report analysis

Bad prompt:
<prompt>
"Analyze this financial report."
</prompt>

Good prompt:
<prompt>
"I've attached our company's Q2 financial report titled 'Q2_2023_Financial_Report.pdf'. Act as a seasoned CFO and analyze this report and prepare a briefing for our board of directors. Please structure your analysis as follows:

1. Executive Summary (3-4 sentences highlighting key points)

2. Financial Performance Overview:
   a) Revenue: Compare to previous quarter and same quarter last year
   b) Profit margins: Gross and Net, with explanations for any significant changes
   c) Cash flow: Highlight any concerns or positive developments

3. Key Performance Indicators:
   - List our top 5 KPIs and their current status (Use a table format)
   - For each KPI, provide a brief explanation of its significance and any notable trends

4. Segment Analysis:
   - Break down performance by our three main business segments
   - Identify the best and worst performing segments, with potential reasons for their performance

5. Balance Sheet Review:
   - Highlight any significant changes in assets, liabilities, or equity
   - Calculate and interpret key ratios (e.g., current ratio, debt-to-equity)

6. Forward-Looking Statements:
   - Based on this data, provide 3 key predictions for Q3
   - Suggest 2-3 strategic moves we should consider to improve our financial position

7. Risk Assessment:
   - Identify 3 potential financial risks based on this report
   - Propose mitigation strategies for each risk

8. Peer Comparison:
   - Compare our performance to 2-3 key competitors (use publicly available data)
   - Highlight areas where we're outperforming and areas for improvement

Please use charts or tables where appropriate to visualize data. For any assumptions or interpretations you make, please clearly state them and provide your reasoning.

After completing the analysis, please generate 5 potential questions that board members might ask about this report, along with suggested responses.

Finally, summarize this entire analysis into a single paragraph that I can use as an opening statement in the board meeting."
</prompt>

Why it's better: This prompt combines role-playing (as CFO), structured output, specific data analysis requests, predictive analysis, risk assessment, comparative analysis, and even anticipates follow-up questions. It provides a clear framework while encouraging deep analysis and strategic thinking.