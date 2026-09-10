# 报告模板

`python scripts/cleanup.py --report` 生成的 Markdown 报告结构如下；
AI 代理以对话形式输出报告时，**沿用同一结构**（可裁剪章节，不可调整分区语义）。

---

## 一、Markdown 报告结构

```markdown
# 代码清理与性能热点报告

- **生成时间**: YYYY-MM-DD HH:MM
- **触发方式**: manual（full） | commit（staged）
- **Git**: `<sha8>` @ `<branch>`
- **扫描范围**: N 文件 / M 行 Python

## 总览

| 指标 | 数量 |
|---|---|
| 清理项（CL-xx） | n |
| 性能项（PF-01~05/07/08） | n |
| 热点候选（PF-06） | n |
| 本轮新增（基线外） | n |
| 预估工时合计 (h) | n |

## 基线状态

| 状态 | 数量 | 占比 |
|---|---|---|
| open | n | x% |
| fixed | n | x% |
| suppressed | n | x% |

存量清偿率 x%

## 规则分布

| 规则 | 含义 | 数量 |
|---|---|---|
| CL-02 | 过时符号（零引用函数/类/常量） | n |
| ... | ... | ... |

## 清理行动清单

> 删除/收敛前必须确认无动态引用（见 skill「安全协议」），分批提交。

### CL-01 冗余文件（import 图零引用）（n）

- **`path/to/file.py:1`** `symbol` — 冗余文件：import 图中无任何入口可达（零引用）
  - 建议: 确认无动态加载/子进程调用后删除（git 历史可恢复）…
  - severity: high | 工时: 0.5h | 指纹: `40d731f30ba3`

## 性能优化清单

> 命中项为静态候选，先用 py-spy / cProfile / EXPLAIN QUERY PLAN 实测再改。

### PF-01 高耗时：循环内 IO/查询（N+1）（n）

- **`path/to/file.py:42`** `<loop>` — 循环内 IO/查询（N+1 风险，嵌套层 1）：execute
  - 建议: 批量化为单次查询/单次请求…
  - severity: medium | 工时: 1.0h | 指纹: `a1b2c3d4e5f6`

## 热点候选（非缺陷）

> 按热度分排序，仅代表实测优先级，不代表存在缺陷。

## 模块分解

| 模块 | 发现数 | 工时 (h) |
|---|---|---|
| backend/api | n | n |

## 趋势（最近全量扫描）

| 日期 | findings | 工时 (h) |
|---|---|---|
```

---

## 二、AI 对话输出模板（面向用户时的收敛格式）

工具报告面向「逐条执行」，对话报告面向「决策」。以对话形式输出时用下面的结构：

```markdown
## 清理与优化盘点（范围 / 模式）

**结论**（2-4 句）：整体冗余水平、最大风险点、本次建议动作。

### 关键发现

| # | 类型 | 位置 | 问题 | 严重度 | 建议动作 |
|---|---|---|---|---|---|
| 1 | 冗余文件 | `path:1` | import 图零引用 | high | 三轮质询后删除 |
| 2 | 性能 | `path:42` | 循环内 execute（N+1） | medium | 批量查询 + EXPLAIN 验证 |

### 建议批次

- **B1 临时遗留**（n 项，零风险）：`rm ...`
- **B2 不可达文件**（n 项，需逐条质询）：…

### 待确认

- `path:line` 是否为休眠运维接口？被 Runbook 引用则保留。
- `PF-xx` 候选需实测：建议先跑 `py-spy record` / `EXPLAIN QUERY PLAN`。

### 覆盖度声明

- 静态扫描覆盖：N 个文件（清理范围 100% / 前端入口 BFS 100%）
- 外部工具：knip（未安装，未执行）/ vulture（已执行，结果已交叉核对）
- 未做：profiler 实测（需用户提供运行场景与数据规模）
```

**语言**：正文用简体中文，代码、标识符、路径、技术术语保留英文原样。

---

## 三、机器可读输出（`--json`）

供 CI / 仪表盘消费，字段固定，可安全依赖：

```json
{
  "trigger": "manual",
  "mode": "full",
  "git_sha": "…",
  "branch": "main",
  "files_scanned": 373,
  "python_loc": 32513,
  "duration_s": 2.53,
  "n_findings": 264,
  "n_new": 264,
  "td_hours": 197.0,
  "findings": [
    {
      "rule_id": "CL-01",
      "title": "冗余文件（import 图零引用）",
      "severity": "high",
      "file": "backend/api/services/broker_storage_service.py",
      "line": 1,
      "symbol": "broker_storage_service",
      "message": "冗余文件：import 图中无任何入口可达（零引用）",
      "fix_hint": "…",
      "fingerprint": "40d731f30ba3…",
      "is_new": true,
      "est_effort_h": 0.5
    }
  ]
}
```

**契约**：`findings[].fingerprint` 跨扫描稳定（符号级规则绑定符号名，位置级规则绑定行号），
可用于跨扫描追踪同一问题的生命周期；`is_new` 表示不在当前基线 `open` 集合内。
