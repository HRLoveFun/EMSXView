# Archive 2026-04-28 — 项目结构清理

这次归档由架构审查触发。所有文件均为一次性临时脚本或已被正式 pytest 套件取代的旧测试。

## 根目录临时脚本

- `_tmp_inspect.py` — sqlite 表结构/行数一次性检查
- `_wait_poll.py` — 一次性等待 + 查询脚本
- `test.ipynb` — 探索性 notebook，4/15 后未维护

## `scripts/` 一次性验证脚本

见 `scripts/_archive/2026-04-28/`：
- `test_derive_exchange.py`、`test_exchange_ticker_fix.py`、`test_order_exchange_ticker.py` — 交易所派生逻辑临时验证
- `test_orders_display_fix.py` — 订单显示修复后验证
- `verify_fetch_20260403.py` — 特定日期数据补抓验证

## `CostView/` 旧测试脚本

见 `CostView/_archive/2026-04-28/`，已由 `CostView/tests/` 下 pytest 套件取代：
- `test_runner.py`、`test_fetch_workflow.py`
- `analyze_route.py`、`verify_route.py` — 一次性路由分析

## 保留说明

未归档的相关文件（仍在维护）：
- `CostView/test_comprehensive.py`、`CostView/test_pipeline_guards.py`
- `项目功能构建规划.md`（路线图）
- `CostView/data/raw_fills.db.bak_before_dedup`（3.4 GB 数据备份，需单独决定）
