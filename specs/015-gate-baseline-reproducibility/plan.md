# 015 — 质量门禁基线可复现性（首次扫描零基线豁免）

> 特性：`015-gate-baseline-reproducibility`
> 分支：`015-gate-baseline-reproducibility`（worktree `../EMSXView-wt-015-gate-baseline-reproducibility`）
> 定位：P0「作业地基」第 2 项
> 决策记录：[ADR-0021](../../docs/spec/adr/0021-gate-first-scan-baseline.md)

---

## 1. 问题（实测证据）

OE 规则集是 **guard 语义**（新增阻断 / 存量放行），存量来自 SQLite 基线库
`scripts/reports/quality_gate/quality_gate.db`；该库**被 `.gitignore` 排除、不入库**，因此每台机器 /
每个 worktree 都是**空库起步**。空库 ⇒ `load_open_fingerprints()` 为空 ⇒ 仓库内全部既有 OE 被判
「新增」⇒ **首次提交被整体误阻断**。

实测：2026-09-16 的 `specs/012`（ExecutionView 迁出 frontend）与 `specs/013`（npm workspaces）两个
任务各命中一次；两次都是靠「先手动跑一次全量扫描灌基线，再提交」绕过。换机器、换 worktree、CI 上会重演。

另有一个语义不可辨问题：`load_open_fingerprints()` 无法区分

| 状态 | open 集合 | 应有语义 |
|---|---|---|
| 首次扫描（库为空） | 空 | 本次即基线快照，不判新增 |
| 存量已全部清偿 | 空 | 已有基线，之后任何出现都是新增 ⇒ 应阻断 |

## 2. 决策

1. `GateStore.has_baseline()`：以「`baseline` 表是否存在任何记录」区分上表两态。
2. `gate_verdict(findings, oe_open_baseline, baseline_established=True)`：`baseline_established=False`
   时全部 OE 记存量、`oe_new` 为空；**AP 违规始终阻断**。
3. 终端显式提示首次扫描已建基线。
4. 清理门禁不改（`STRICT_ENFORCEMENT=False`，本就非阻断）。

## 3. 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `scripts/quality_gate/store.py` | 新增 `has_baseline()` |
| 2 | `scripts/quality_gate/scoring.py` | `gate_verdict` 增 `baseline_established` 参数与首次扫描分支 |
| 3 | `scripts/quality_gate/run.py` | 读取 `has_baseline()` 并传入判定；首次扫描提示 |
| 4 | `scripts/quality_gate/tests/test_gate_verdict.py` | 新增：存量/新增划分、首次扫描放行、AP 不豁免、`has_baseline` 不因「已清偿」退化 |
| 5 | `docs/spec/quality-gate.md` | §基线演进 补首次扫描语义与 ADR 链接 |
| 6 | `docs/spec/adr/0021-gate-first-scan-baseline.md` | 新增 ADR |
| 7 | `docs/spec/memory.md`、`docs/spec/adr/README.md` | ADR 索引 |
| 8 | `specs/015-gate-baseline-reproducibility/plan.md` | 本文件 |

## 4. 验收

| 需求 | 检验方法 |
|---|---|
| 空库不再误阻断 | 在无基线库的新 worktree 跑 `python scripts/quality_gate.py --ruleset oe --quiet`，**退出码 0** 且输出「首次扫描…本轮不判定新增」（改前为退出码 1） |
| 第二次扫描恢复 guard 语义 | 紧接再跑一次，退出码 0；人工插入一条新 finding（改文件使其超阈）后应退出码 1 |
| AP 不受豁免 | 单测覆盖；实际 AP 违规仍阻断 |
| 「已清偿」不退化为首次扫描 | 单测 `test_all_open_items_fixed_still_counts_as_established` |
| ADR 索引一致 | `python scripts/audit_doc_drift.py`（21→22 ADRs indexed） |
| 既有检测器行为不变 | `python -m pytest scripts/quality_gate/tests/ -q` 全绿 |

## 5. 风险

- **首次扫描吸收真实新增债务**（已知取舍）：在空库的那一次扫描里新引入的 OE 不报。缓解：显式提示 +
  本决策目标为「不恶化」而非强门禁；全量扫描仍是权威。
- **跨机判定仍可能不同**：彻底方案是把基线快照入库（ADR-0021 备选方案 A），本次不采用。
- **回滚**：单一提交，`git revert` 即恢复「空库 = 全量阻断」。

## 6. 本次不做

- 不把基线快照入库（ADR-0021 备选方案 A）。
- 不改动清理门禁（`scripts/cleanup/`）的判定与基线机制。
- 不动 AP 规则集的阻断语义。
