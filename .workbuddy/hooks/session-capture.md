# Session Capture Hook

> 自动捕获会话关键信息，辅助生成 HANDOFF.md 更新

## 功能定位

这是一个**半自动化工具**，用于降低手动记录 HANDOFF.md 的负担，而非完全替代人工判断。

## 触发时机

### 方案 A：定期触发（推荐）

**触发条件**: 每天 18:00（工作日）  
**检测逻辑**:
```
1. 检查当天是否有新的聊天记录文件
2. 读取当天的会话内容
3. 提取关键信息
4. 生成 HANDOFF 更新建议
5. 提示用户确认
```

### 方案 B：关键词触发

在会话中检测到以下关键词时自动记录：
- " blocker" / "阻碍" / "卡住"
- "TODO:" / "FIXME:" / "待办"
- "decision:" / "决策" / "决定"
- "error:" / "错误" / "报错"
- "resolved:" / "解决" / "已修复"

### 方案 C：手动触发

用户主动执行：
```
"/capture" 或 "记录到 HANDOFF"
```

## 自动捕获内容

### 结构化信息模板

```yaml
session_capture:
  timestamp: 2026-03-16T14:30:00
  type: "blocker_resolved"  # blocker_resolved | decision_made | task_completed | error_fixed
  
  summary: "解决了 Bloomberg API 连接超时问题"
  
  context:
    problem: "EMSX API 返回连接超时错误"
    cause: "防火墙阻止了端口 8194"
    solution: "联系 IT 开放端口，添加防火墙规则"
  
  related_files:
    - "emsx-backend/backend/main.py"
    - "docs/ERROR_PATTERNS.md"
  
  follow_up:
    - "验证其他环境是否受影响"
    - "更新部署文档"
  
  status: "pending_review"  # pending_review | confirmed | discarded
```

## 与 HANDOFF.md 的集成

### 自动写入位置

捕获的信息暂存到 `docs/session_captures/` 目录：
```
docs/session_captures/
├── 2026-03-16/
│   ├── capture-001-blocker.md
│   ├── capture-002-decision.md
│   └── summary.md
```

### 定期合并任务

**任务名称**: `handoff-merge-daily`  
**执行时间**: 每天 19:00  
**执行逻辑**:
```python
1. 读取 docs/session_captures/ 下当天的所有捕获文件
2. 过滤出 status = confirmed 的条目
3. 按 HANDOFF.md 格式整理
4. 提示用户审核
5. 用户确认后追加到 HANDOFF.md
6. 清空当天的捕获缓存
```

## 实施步骤

### 步骤 1：创建捕获目录结构

```bash
mkdir -p docs/session_captures/$(date +%Y-%m-%d)
```

### 步骤 2：配置关键词监听

在项目根目录创建 `.workbuddy/hooks/on-keyword.json`：
```json
{
  "triggers": [
    {"pattern": "(blocker|阻碍|卡住)", "type": "blocker"},
    {"pattern": "(decision|决策|决定)", "type": "decision"},
    {"pattern": "(resolved|解决|已修复|fixed)", "type": "resolution"},
    {"pattern": "(error|错误|报错|exception)", "type": "error"},
    {"pattern": "(TODO|FIXME|待办|待处理)", "type": "task"}
  ],
  "action": "capture_context",
  "output": "docs/session_captures/{date}/capture-{seq}-{type}.md"
}
```

### 步骤 3：创建自动化任务

**任务**: `session-capture-daily`
```toml
name = "session-capture-daily"
prompt = """
请执行以下任务来自动化 HANDOFF.md 的更新流程：

1. 读取今天的聊天记录（如果有）
2. 识别关键事件：
   - 阻碍/卡点
   - 做出的决策
   - 完成的任务
   - 解决的错误
   - 待办事项

3. 为每个关键事件生成捕获文件：
   - 保存到 docs/session_captures/YYYY-MM-DD/
   - 文件格式: capture-XXX-{type}.md
   - 内容包含：摘要、上下文、相关文件、后续行动

4. 生成当天的摘要汇总到 summary.md

5. 提示用户查看并确认
"""
rrule = "FREQ=DAILY;BYHOUR=18;BYMINUTE=0"
cwds = ["c:/Users/hrchen/Documents/EMSX"]
status = "PAUSED"  # 用户确认后改为 ACTIVE
```

**任务**: `handoff-merge-daily`
```toml
name = "handoff-merge-daily"
prompt = """
请将今天捕获的会话信息合并到 HANDOFF.md：

1. 读取 docs/session_captures/YYYY-MM-DD/summary.md
2. 按 HANDOFF.md 格式整理：
   - Recent Blockers（已解决的阻碍）
   - Open Blockers（未解决的阻碍）
   - Decisions Made（做出的决策）
   - Next Tasks（下一步任务）

3. 提示用户审核整理后的内容
4. 用户确认后追加到 HANDOFF.md
5. 将已合并的捕获文件移动到 archived/ 目录
"""
rrule = "FREQ=DAILY;BYHOUR=19;BYMINUTE=0"
cwds = ["c:/Users/hrchen/Documents/EMSX"]
status = "PAUSED"
```

## 实际使用流程

### 场景 1：日常开发（自动捕获）

```
用户: 遇到了一个问题，Bloomberg API 连接超时
AI:   我来帮你排查...
...
用户: 解决了！是防火墙问题
      ^^^^^^^^ 触发关键词 "解决"

[系统自动捕获]
├── 检测到关键词: "解决"
├── 提取上下文: Bloomberg API 连接超时 → 防火墙
├── 生成文件: docs/session_captures/2026-03-16/capture-003-resolution.md
└── 状态: pending_review

[18:00 自动执行 session-capture-daily]
├── 汇总当天捕获: 3 条
├── 生成 summary.md
└── 提示用户: "今天有 3 条捕获待确认，是否查看？"

[用户确认]
├── 用户: "确认"
└── [19:00 自动执行 handoff-merge-daily]
    ├── 读取 summary.md
    ├── 追加到 HANDOFF.md
    └── 移动到 archived/
```

### 场景 2：主动触发

```
用户: /capture 记录当前决策

AI: 已捕获当前上下文。
    摘要: "决定使用 Zustand 替代 Context 进行状态管理"
    类型: decision
    
    是否现在确认？
    [确认] [修改] [取消]

用户: 确认

AI: 已保存到 docs/session_captures/.../capture-004-decision.md
    将在今天的汇总中合并到 HANDOFF.md
```

### 场景 3：批量确认（推荐）

```
[18:00 自动提醒]
AI: 今天检测到 5 个关键事件：
    1. [阻碍] Bloomberg API 未启用 → 已记录
    2. [决策] 采用 shadcn/ui 组件库 → 已记录
    3. [解决] WebSocket 重连问题 → 已记录
    4. [任务] 添加 pytest 测试 → 已记录
    5. [错误] EMSX_CURRENCY 无效 → 已记录

    是否一键确认全部？
    [确认全部] [逐个查看] [忽略今日]

用户: 逐个查看

[用户逐条确认或修改]
└── 确认后自动准备合并

[19:00 自动合并]
└── 更新 HANDOFF.md
```

## 优势与局限

### 优势

1. **降低记录负担**: 自动提取关键信息，减少手动整理
2. **不丢失上下文**: 捕获当时的完整对话背景
3. **灵活可控**: 人工确认后才写入正式文档
4. **可追溯**: 所有捕获都有存档，便于回顾

### 局限

1. **无法 100% 自动化**: 需要人工判断哪些信息值得记录
2. **关键词可能误判**: 需要调优触发规则
3. **隐私考虑**: 可能捕获敏感信息，需要过滤机制

## 与 SESSION_DIGEST 的衔接

```
日常会话 → 自动捕获 → 临时存储 → 人工确认 → HANDOFF.md
                                              ↓
                                       [每周自动化]
                                              ↓
                                       SESSION_DIGEST.md
                                              ↓
                                       [每月审核]
                                              ↓
                                  ERROR_PATTERNS / MEMORY.md
```

## 下一步行动

1. **试运行**: 先启用关键词捕获，观察 1 周
2. **调优规则**: 根据实际触发情况调整关键词
3. **逐步自动化**: 确认可靠后启用每日自动汇总
4. **评估效果**: 1 个月后评估是否减少了手动记录负担
