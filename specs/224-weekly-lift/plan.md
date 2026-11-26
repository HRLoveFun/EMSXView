# 224 — 信号/规则周度回检与周任务

> 父计划：DL-26（221 月度 CLI）
> 分支：`224-weekly-lift`

## 问题

1. DL-26 CLI 只有月/显式区间，用户要求改为**周度**自动任务。
2. 区间内没有 `tca_route_summary` 行时，CLI 仍返回 0，会把管道滞后误报成「0 样本成功」。

## 方案

- `scripts/qa/signal_lift_report.py` 新增 `--week`：上一个完整自然周（周一至周日）。
- 无行守卫：区间内 `routes == 0` 时打印最新汇总日期并返回 **3**（报告仍落盘供追溯）。
- 注册任务 `EMSXView-Signal-Lift-Weekly`：每周一 07:20 运行 `--week`，日志追加到
  `logs/qa/signal_lift/weekly-task.log`。
- 文档：CostView/scripts README 标注月度/周度双模式与退出码。

## 验收

- `--week` 正确解析上一个周一至周日；与 `--month/--start/--end` 互斥。
- 空区间返回 3，消息含 `latest summary date`。
- 任务已注册且 `NextRunTime` 为下周一 07:20。

## 数据前置（重要）

2026-11-26 检查：`tca_route_summary` 最新交易日为 **2026-11-13**，而上游 `raw_fills`
已到 11-23。周任务在下游管道 S5.5 补跑前会持续 exit 3；这是**数据管道滞后**，不是 CLI 缺陷。

## 范围锁

- `scripts/qa/signal_lift_report.py`、`CostView/README.md`、`scripts/README.md`、
  `specs/057-execution-decision-loop/tasks.md`、`specs/224-weekly-lift/plan.md`
- 任务注册（本机任务计划程序，非代码）
