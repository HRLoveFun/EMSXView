# ADR-0021: 质量门禁首次扫描自动建基线（OE guard 的零基线豁免）

> 状态: Accepted
> 日期: 2026-09-16
> 标签: process, tooling, quality-gate

## 背景 (Context)

质量门禁的 OE 规则集采用 **guard 语义**（新增阻断 / 存量放行），存量集合来自 SQLite 基线库
`scripts/reports/quality_gate/quality_gate.db`。该库被 `.gitignore` 排除，**不入库**，因此：

- 每台机器、每个 git worktree 都有**各自独立、初始为空**的基线库；
- 判定逻辑为「fingerprint 不在 open 基线集合中 ⇒ 判为新增 ⇒ 阻断」。

当基线库为空时，仓库里所有既有 OE 项都会被判成「新增」——**新克隆 / 新 worktree 的第一次提交会被
仓库既有债务整体误阻断**。2026-09-16 的 012、013 两个任务各命中一次，两次都只能靠「先手动跑一次
全量扫描把基线灌满，再提交」绕过；这不是可持续的作业方式（换机器、换 worktree、CI 上都会重演）。

同时，`load_open_fingerprints()` 的返回值**无法区分**两种语义完全相反的状态：

| 状态 | open 集合 | 应有语义 |
|---|---|---|
| 首次扫描（库为空） | 空 | 本次结果即基线快照，不判新增 |
| 存量已全部清偿 | 空 | 已有基线，之后任何出现都是新增 → 应阻断 |

## 决策 (Decision)

1. 新增 `GateStore.has_baseline()`：判断基线库中是否存在任何 `baseline` 记录（而非「是否有 open 项」）。
2. `gate_verdict(findings, oe_open_baseline, baseline_established=True)`：当
   `baseline_established=False`（首次扫描）时，**全部 OE 记为存量、`oe_new` 为空**；
   **AP 契约违规不受影响**，始终阻断（契约违规与基线无关）。
3. 终端输出显式提示：`首次扫描：已建立 OE 基线（N 项），本轮不判定新增 —— 后续扫描按基线演进`。
4. 清理门禁（`scripts/cleanup/`）不改：其 `STRICT_ENFORCEMENT=False` 本就非阻断，无此脚坑。

## 后果 (Consequences)

### 正面

- 去除「新 worktree 首提交必被误阻断」的脚坑，作业流程与新机器上机流程可复现。
- 「首次扫描」与「已清偿」在代码与文档层面被显式区分（此前两者不可辨）。
- 语义可测：`scripts/quality_gate/tests/test_gate_verdict.py` 锁定四条边界。

### 负面 / 取舍

- **首次扫描存在小漏洞**：在库为空的那一次扫描里引入的真实新增 OE 债务会被基线吸收而不报。
  缓解：首次扫描会打印显式提示；且基线演进的目标本就是「不恶化」，而非「一次到位的强门禁」。
- 门禁结果依然**依赖本机基线库**：不同机器判定的「新增」集合仍可能不同。彻底解决需把基线快照入库
  （见备选方案 A），本 ADR 不采用，仅消除「空库即全量阻断」这一最痛的分支。

### 对其他 ADR 的影响

- 关联: [ADR-0017](0017-cleanup-and-perf-hotspot-mechanism.md)（清理/性能门禁复用同一套基线基础设施）；
  本决策只改 OE guard 的**空库分支**，不动基线生命周期（upsert / fixed / suppressed）。

## 备选方案 (Considered Alternatives)

- **方案 A：把基线快照入库（JSON），各机器共用一份**
  - 否决原因：需新增「快照更新」流程与冲突处理；跨平台指纹稳定性（路径 / 行号漂移）会制造大量假新增；
    收益（跨机一致）在当前单人 + 多 worktree 的现实下不足以抵消成本。
- **方案 B：保持现状 + 在文档写明「新 worktree 先跑一次全量扫描」**
  - 否决原因：脚坑仍在，且实测两次都是靠临时救火绕过——文档留不住这类约定。
- **方案 C：无基线时不阻断，但也不写基线**
  - 否决原因：违背基线演进设计（下次扫描依旧为空、永远不判新增），等于永久关闭 OE 门禁。

## 实施注意事项 (Implementation Notes)

- 涉及的关键文件：`scripts/quality_gate/store.py`（`has_baseline`）、`scripts/quality_gate/scoring.py`
  （`gate_verdict`）、`scripts/quality_gate/run.py`（首次扫描提示）、`docs/spec/quality-gate.md`。
- 配套测试：`scripts/quality_gate/tests/test_gate_verdict.py`（存量/新增划分、首次扫描放行、
  AP 不豁免、`has_baseline` 对「已清偿」不退化）。
- 回滚策略：单一提交，`git revert` 即恢复「空库 = 全量阻断」行为。
