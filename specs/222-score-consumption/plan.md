# 222 — BrokerScoreSnapshot 消费（DL-24 → DL-25 辅助预填）

> 父计划：`specs/057-execution-decision-loop` 的 **DL-24 / DL-25**（节点三出口判据「得分快照被分配引擎消费」）
> 分支：`222-score-consumption`（基于 `origin/main`）
> 依赖：DL-24（217 已交付）、DL-25（219/220 已交付）

---

## 1. 问题

1. `BrokerScoreSnapshot` 目前只有报告章节与 `GET /api/tca/broker-scores`，**没有任何消费方**；节点三「得分快照被分配引擎消费」未满足。
2. DL-24 的预留接口写明「供 DL-25 打分与 DL-27 轮换」，但 219 预填只聚合影子决策，未使用分项得分。
3. 契约要求 `available=False` 时 `value=None`，但 `tail_risk` 在只有 1 个 z 样本时返回 `0.0`（把「不可得」写成「零风险」）。

---

## 2. 方案（只读消费，不改比例）

### S1 · 前端类型与 API

- `types/broker.ts`：`BrokerScoreComponent` / `BrokerScoreSnapshot` / `BrokerScoresResponse`（与后端 JSON 对齐）。
- `broker-api.ts`：`getBrokerScores({startDate,endDate,broker,algo})` → `GET /api/tca/broker-scores`。

### S2 · 预填理由中的分项得分

- `prefill.ts` 增加可选 `scoresByBroker`；输出 `scoreNotes`（如 `cost 4.21 bps (n=120)`）、`scoreWindow`、`scoresUsed`。
- **不改变券商顺序与比例**：分项只进入预填提示/理由，交易员仍逐笔确认。
- `use-batch-route-state.prefillFromShadow`：预填时取最近 90 天快照，取 `cost` 分项附加到提示；取数失败/评估层关闭 → 预填照常、明确提示得分不可得。
- 不改后端提交链路、不改 `route_order` 请求。

### S3 · 契约修复

`CostView/src/evaluation/broker_score.py`：`tail_risk.value` 仅在 `len(z_values) >= 2` 时计算，否则 `None`；补回归测试。

### S4 · 月度 lift 归档（同一推进批次）

- 已用生产库补跑 **2026-10**：`logs/qa/signal_lift/signal_lift_20261001_20261031.json`（24,978 路由 / 23,137 可用 / 16,619 单）。
- 建议注册每月 1 日 07:20 的任务，自动生成上一个自然月报告（下一步）。

---

## 3. 范围锁

- `ExecutionView/module/types/broker.ts`
- `ExecutionView/module/services/broker-api.ts`
- `ExecutionView/module/components/batch-route-order/prefill.ts` + `prefill.test.ts`
- `ExecutionView/module/components/batch-route-order/use-batch-route-state.ts`
- `CostView/src/evaluation/broker_score.py` + `CostView/tests/test_broker_score.py`
- `specs/057-execution-decision-loop/tasks.md`

**不做**：不合成综合分（D-5）；不用得分改变券商比例或数量（属 DL-27，需 D-2 预算与权重口径）；不改后端 `/api/tca/broker-scores` 契约。

---

## 4. 验收

1. 预填在有得分快照时显示 `cost` 分项与窗口；无快照/评估层关闭时预填不降级、明确提示。
2. 分项不改变券商顺序、比例与 decision_id。
3. `available=False` 的分项 `value=None`（回归测试）。
4. `tsc -b`、`pytest CostView/tests/test_broker_score.py`、`doc_check.py` 全绿。

---

## 5. 风险与边界

- **不等于「比例消费」**：本 PR 只把分项作为 ASSIST 理由暴露；真正的分配权重/轮换消费在 DL-27，需 D-2 预算口径，默认关闭。
- **取数延迟**：90 天窗口 + 2000 路由上限，预填点击时多一次查询；失败不影响预填。
- **样本不足**：`low_sample` 与 `available=False` 均已透出，不用 0 填充。
