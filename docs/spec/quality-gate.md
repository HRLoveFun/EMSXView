# 质量门禁框架（Quality Gate）

> **状态**：实施中（2026-08-21）
> **代码**：`scripts/quality_gate/` 包 + `scripts/quality_gate.py` 平铺入口
> **规则**：AP-xx 契约违规（包装既有 `audit_*.py`）+ OE-xx 过度工程（自研 AST 检测器）

## 设计动机

监测机制本身不能成为过度工程。本框架将两类规则统一于一套基础设施：
- **AP-xx 契约违规**：确定性规则（import 某路径 = 违规），零误报，立即阻断
- **OE-xx 过度工程**：启发式阈值判断，有固有误报，基线演进（新增阻断/存量放行）

两者共用 CLI、SQLite 基线、Markdown 报告、pre-commit 集成，避免重复建设。

## 与 anti-patterns.md 的关系

- `docs/spec/anti-patterns.md` 是 AP-xx 规则的文档清单（AI 必查入口）
- 本文档是 OE-xx 规则 + 框架基础设施的设计文档
- `anti-patterns.md` 顶部索引指向本文档（交叉引用）

## CLI 用法

```bash
# 全量扫描（手动触发，建基线 / 趋势追踪）
python scripts/quality_gate.py

# 全量扫描 + Markdown 技术债报告
python scripts/quality_gate.py --report

# 增量模式（pre-commit 用，stdin 接收暂存文件列表）
git diff --cached --name-only | grep -E '\.(py|ts|tsx)$' \
  | python scripts/quality_gate.py --staged --quiet

# 仅运行 AP 契约审计（快速）
python scripts/quality_gate.py --ruleset ap --quiet

# 人工豁免误报
python scripts/quality_gate.py --suppress <fingerprint> --note "理由"
```

## OE 规则清单

| ID | 检测 | 算法 | 阈值 |
|----|------|------|------|
| OE-01 | 冗余模块 | import 图可达性（含 f-string 动态导入兜底） | 入口白名单见 config.py |
| OE-02 | 过度抽象 | 单实现 ABC / 1:1 传递函数 | 单实现 <50 行 |
| OE-03 | 不必要设计模式 | 过深继承链 / 单产品工厂 | 继承链 >3 层 |
| OE-04 | 重复代码块 | AST 归一化 + 整函数体匹配 | ≥30 行等价块 |
| OE-05 | 复杂度超标 | 圈复杂度/嵌套/参数/长度 | CC>15 / 嵌套>4 / 参数>7 / 函数>120 行 |
| OE-06 | 前端未使用导出 | import/export 名字图 | 全库无消费者 |
| OE-07 | 前端超长组件 | 文件行数 / useState 计数 | 行数>400 / hooks>10 |

阈值集中定义于 `scripts/quality_gate/config.py`，调优只改该文件。

## 量化模型

- **Finding**：`{rule_id, severity, file, line, symbol, message, fix_hint, fingerprint, est_effort_h}`
- **fingerprint** = `sha1(rule_id + 归一化代码段)`，跨扫描追踪同一问题的生命周期
- **OEW 分**：`Σ(severity 权重 × OE 数量) / KLoC`，权重 high=3 / medium=2 / low=1
  - 分档：<2 健康 / 2-5 需关注 / >5 快速累积期
- **技术债工时**：`Σ est_effort_h`（仅 OE 计入，AP 不计工时）
- **趋势**：与上次全量扫描对比 delta（新增/修复/存量）

## 基线演进

| 阶段 | 模式 | 行为 |
|------|------|------|
| Phase 1 record | OE_ENFORCEMENT=guard | 新增阻断、存量放行、修复正向提示 |
| Phase 2 block | OE_ENFORCEMENT=block | 存量清零后可切换为全量阻断（预留） |

- full 扫描后自动标记本轮未见的 open 项为 fixed
- 误报治理：`--suppress <fingerprint> --note "理由"` 或文件级豁免清单

## pre-commit 集成

`.githooks/pre-commit` 在暂存文件含 `.py/.ts/.tsx` 时执行 `quality_gate.py --staged`：
- AP 适配层仍调用既有 `audit_*.py` 三个脚本（零重写零回归）
- OE 检测器受 25s 预算 fail-open 保护（监测器故障不阻断正常开发）
- AP 检测器异常不 fail-open（契约防线语义）

## 自反性约束

框架自身遵守的过度工程禁令：
- 零第三方依赖（纯标准库 ast/sqlite3/hashlib）
- 检测器共享 ast_utils，单文件 <300 行
- staged 路径严格限时 + fail-open
- 不为统一而重写既有 `audit_*.py`（ap_adapter 只做包装）
- 不迁移 `tests/boundaries/` pytest 套件（独立演进，避免迁移风险）

## 产出

- 趋势库：`scripts/reports/quality_gate/quality_gate.db`（scans/findings/baseline 三表）
- 报告：`scripts/reports/quality_gate/report-YYYYMMDD.md`
