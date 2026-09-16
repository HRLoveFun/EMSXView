# Golden 快照回归（TCA 指标锁定）

本目录固化 CostView TCA 指标计算的回归基线，防止 SQL / 口径改动导致数值漂移。

## 资产构成

| 资产 | 作用 | 是否入库 |
|---|---|---|
| `*.json`（如 `20260901_20260904.json`） | 基线：锁定路由的关键指标期望值（200 条 × 18 项，含每指标相对容差） | ✅ 入库 |
| `snapshot/fill_bdib.db` | 与基线**同源**的冻结输入（仅 `tca_route_summary` 本区间行集，约 1.5 MB） | ✅ 入库（测试夹具） |
| `CostView/scripts/make_golden_snapshot.py` | 从生产库**只读**裁剪快照 | — |
| `CostView/scripts/gen_golden.py` | 由快照生成 / 刷新基线 JSON | — |

快照存在的理由：生产 `fill_bdib.db` 达 GB 级且内容随每日更新漂移，而回归只需要
指定区间的 `tca_route_summary` 冻结行集。把它作为**测试夹具**入库后，CI 与本地
无需访问生产数据即可执行指标锁定。

## 运行

```bash
# 默认：使用仓库内置快照（无需生产数据，与 CI 同路径）
python -m pytest CostView/tests/test_golden_samples.py -q

# 覆盖：指向其他同源快照目录（含 fill_bdib.db）
EMSXVIEW_GOLDEN_DATA_DIR=/path/to/snapshot python -m pytest CostView/tests/test_golden_samples.py -q
```

CI：`.github/workflows/boundary.yml` 的 `backend-tests` job 已包含
“Golden snapshot 回归 (CostView 指标锁定, 硬阻断)” 步骤。

## 基线更新 SOP（唯一写入路径）

> 前提：能只读访问生产 `fill_bdib.db`（默认 `Config.FILL_BDIB_DB`）。
> **快照与 JSON 必须同次产出**，否则 `total_routes` 与指标会对不上。

```bash
# 1. 重建快照（只读裁剪，覆盖入库夹具）
python CostView/scripts/make_golden_snapshot.py --start <START> --end <END>

# 2. 由同一快照重建基线 JSON
python CostView/scripts/gen_golden.py --data-dir CostView/tests/golden/snapshot \
    --start <START> --end <END>

# 3. 人工 review diff —— 每处数值变化都要能对应到具体的口径 / 代码变更
git diff CostView/tests/golden/

# 4. 跑回归确认
python -m pytest CostView/tests/test_golden_samples.py -q
```

**纪律**：

- 禁止把 `EMSXVIEW_GOLDEN_DATA_DIR` 指向生产数据目录（每日更新会使基线失效）。
- 基线 diff 必须逐条可归因；无法解释的漂移先查代码，不要直接改基线。
- 快照是**测试夹具**而非运行时数据：`.gitignore` 的「数据文件不入库」规则对本目录
  有显式例外（`!CostView/tests/golden/snapshot/*.db`）。
- **覆盖边界**：golden 只走 `gen_golden.py` → `build_tca_report` 的 per_order 指标
  链路，**不覆盖 monitoring 侧路径**（报告聚合 / 异常明细 / BDIB 健康扫描——
  fx 回填 CTE `report_measure.fbfx_cte` 仅在这些路径生效）。改 monitoring 口径
  时 golden 不会兜底，安全网是 `tests/test_monitoring.py` /
  `tests/test_report_metrics.py` 的口径断言（`fx_coverage`、`notional_usd` 等），
  改动后必须全量跑 `pytest CostView/tests/` 而非只跑 golden。

## 回归记录

| 日期 | 范围 | 结果 | 说明 |
|---|---|---|---|
| 2026-09-11 | 20260901~20260904（4668 routes，锁定 200 条） | ✅ 1 passed（`CostView/tests/` 全量 170 passed, 0 skipped） | ADR-0018 口径变更（仅影响报告聚合 / 渲染层）落地后回归：订单级指标计算链路零漂移。此前因未设置 `EMSXVIEW_GOLDEN_DATA_DIR` 而永久 skip，本次改为内置快照 + CI 步骤常态化。 |
