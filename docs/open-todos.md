# 全局待办清单（Open TODOs）

> 聚合各计划文件（`specs/*/checklists/progress.md`）末尾的"遗留"小节与未收尾事项，
> 作为跨计划的单一待办入口，避免遗留项散落丢失。
>
> 状态标记：⏳ 待办 / ✅ 已完成 / 🔴 阻塞
> 维护约定：每完成一项更新状态并记录完成日期；来源计划关闭时，对应行可移除。
> 归档提示（2026-09-21）：spec 完成后归档至 `docs/archive/<YYYY-MM-DD>/<feature-id>/`（**保留原编号与目录名**）；
> `specs/009~028` 与 `028b` 已全部归档，`specs/` 当前为空（该目录只承载在途计划），本清单「来源」列与活文档中的历史引用一律指向归档路径。

## 待办

| # | 事项 | 来源 | 状态 | 备注 |
|---|------|------|------|------|
| T1 | PR 合并回 main（004-backend-test-stabilization） | `docs/archive/2026-09-16/004-backend-test-stabilization/checklists/progress.md` | ✅ | 已合并（PR #3）；spec 于 2026-09-16 归档 |
| T2 | PR 合并回 main（005-bloomberg-quota-pause） | `docs/archive/2026-09-16/005-bloomberg-quota-pause/checklists/progress.md` | ✅ | 已合并（merge `fb645d0`）；spec 于 2026-09-16 归档 |
| T3 | `frontend/src/modules/costview/lib/monitoring-metrics.ts:42` fill label 文案 `'成交率'` 改为 `'成交股数'` | `docs/archive/2026-09-16/006-costview-html-report/checklists/progress.md` 遗留 | ✅ | 已核实修好（2026-09-16）：现文件 `CostView/module/lib/monitoring-metrics.ts:47` 为 `fill: '成交股数'`，全文无 `'成交率'` 残留 |
| T4 | `tca_route_summary.fx_rate` 历史回填 | `docs/archive/2026-09-16/007-costview-report-filters/checklists/progress.md` 遗留 | ✅ | 2026-09-01 诊断验证全量 0% NULL（8/26 全量重算 + backfill_tca_route_fx 已覆盖） |
| T5 | 异常明细 arrival_cost_bps / opportunity_cost / wagner_is_bps / cost_cvar / order_duration_sec / recovery_truncated 真实库 100% NULL（Phase 0/1 核心指标列从未回填）；需重跑 S3 管道回填 | `docs/archive/2026-09-16/008-costview-anomaly-detail/plan.md` 调查结论 | ✅ | 2026-09-01 诊断验证：p_arrival/wagner_is 覆盖 87-95%（8/27-28 全量重算已回填），残余 ~3% 为 bdib_missing 真缺口 |
| T6 | 异常明细筛选规则 `fill_pct` 后端映射 bug 已修正：原用 `fill`(股数)比对阈值（永远不触发），现对齐前端用完成率百分比 | `docs/archive/2026-09-16/008-costview-anomaly-detail/plan.md` | ✅ | 后端 `anomaly_query._METRIC_MAP` fill_pct → completion_rate×100 |
| T7 | 异常明细完成率计算经核实正确（`fill/RouteShares`，0% NULL）；无需改动 | `docs/archive/2026-09-16/008-costview-anomaly-detail/plan.md` 调查结论 | ✅ | — |
| T8 | CostView 指标覆盖率修复：① 计划任务 CostView_DailyUpdate 被禁用致日更断流 8/27-8/31（已 re-enable + 回补）；② bar 时间戳区间语义对齐（纯竞价路由末 bar fallback，修复 par_rate/pnl_vwap/par_rate_close 大面积 NULL）；③ 覆盖率分母剔除白名单外交易所 + SLA 豁免口径 | `008-costview-report-enhancement` 分支 | ✅ | 2026-09-02 终验：全量 180 日重算完成，par_rate 全量 NULL 60%→20%，SLA 口径下 continuous 类 52→81%；调度恢复后日更已自动产出 9/1 数据 |
| T9 | 重算 20260901 的 temp_impact/perm_impact（next_day_close 结构性延迟：需等 9/3 日更产出 9/2 daily_summary 后执行 `recompute_all_tca_route_metrics.py --dates 20260901`） | `008-costview-report-enhancement` | ⏳ | 8/31 已于 9/2 补重算回填（temp5 20.6→60.0%、perm 0→54.2%）；9/1 同理待次日数据 |
| T10 | 「打开/切换目标时回填表单 state」类重构（4 处）：`route-plan-manager.tsx`、`unified-modify-route-dialog.tsx` | `docs/archive/2026-09-21/020-react-hooks-set-state-debt/plan.md` | ✅ | 2026-09-16 完成（`docs/archive/2026-09-21/021-t10-form-reset-refactor`）：改「state 初值取自 props + 调用方 key 重挂载」，删除 69 行回填 effect；新增 5 条契约测试；CI 已接入 `npm run lint` + `npm run lint:modules`（硬阻断） |
| T11 | 复核 6 处「与外部系统同步」类 `set-state-in-effect` 豁免 | `docs/archive/2026-09-21/020-react-hooks-set-state-debt/plan.md` | ✅ | 2026-09-16（`docs/archive/2026-09-21/022-t11-async-data-layer`）：新增仓库内取数层 `@shared/hooks/use-async-data`（loading 由 key 派生、setState 只在回调内，7 条契约测试），**5 处 fetch 豁免全部删除**；第 6 处（对账）转 T12 |
| T12 | `use-batch-route-state.ts` 对账逻辑派生化：`rows` 改为由 `orders × rowState × selectedBrokers` 派生，对账 effect 删除 | `docs/archive/2026-09-21/022-t11-async-data-layer/plan.md` §4 | ✅ | 2026-09-21 完成（`docs/archive/2026-09-21/023-t12-batch-route-derive` 测试网 + `docs/archive/2026-09-21/024-t12-rows-derive` 派生化）：两个对账 effect 删除，写入口改为以派生视图为基准；`paramsBuildersRef` 副作用移出 updater（StrictMode 二次执行隐患同时消除）。顺带修正「新增行不补槽」的不对称与 023 用例拿 `undefined` 当券商的问题 |
| T13 | 归档 spec 的未收尾事项：① EMSXDataPipeline 侧 Runner 常驻部署（`emsx-runner` :8100）/ 独立仓 CI 回归 / `PIPELINE_REPORT_CMD` 报告钩子；② `.codebuddy/rules/module-boundary.md` 双仓边界条目（`data_access` 只读层 + 禁 import DataPipeline）；③ 三模块独立部署评估（iframe / Module Federation） | `docs/archive/2026-09-21/010-extract-pipeline/plan.md` TODO-2~5；`docs/archive/2026-09-21/012-executionview-root-extract/plan.md` §7.3 | ⏳ | 2026-09-21 随 spec 归档由计划末尾转记于此（此前的 TODO-1 已完成、TODO-6 已失效）；三项均属本仓库之外的后续/可选演进 |
| T15 | 归档 spec 的未收尾事项（026）：**可选上游物化需求** —— 请上游将 `adv_20d` / `daily_volatility` 物化到 `tca_route_summary` 列（触发条件：跨库读取覆盖率不足或报告耗时不可接受） | `docs/archive/2026-09-21/026-costview-algo-eval/plan.md` §6 U-1 | ⏳ | 2026-09-21 随 spec 归档由计划 §6 转记于此；属**可选性能优化型、非正确性前置**（阶段二实测本侧可经 `bdib_daily_summary` 自给：`adv_20d` 99.39% / `daily_volatility` 99.94%，未触发）。原同批的 U-2（`fill_bdib` 与 `raw_bdib` 两表 `mkt_timestamp` 口径统一）经 Q2-4 实测**两表同格式**（均 8 字符纯时间），**不触发**，故不计入本条 |
| T17 | 上游 2026-04-22 批次中 **168 行 `daily_volatility ≥ 3`** 的边界清单核对 | 上游答复 2026-09-22（第二轮提供清单 / 第三轮给出权威核对） | ✅ | 上游用 Bloomberg 原始 `VOLATILITY_30D` 核对（165 可配对行，`ratio` 中位 **10.78**，落 1 附近 0 行、落 100 附近 0 行）→ 该批**不是**常数缩放；本侧此前用 `daily_close` 自算的抽查因窗口/口径差异**精度不足以定方向**，以权威源为准 |
| T19 | **4-22 批次权威覆盖**（用 Bloomberg 原始值替换近似 ×100 值） | 上游通知 2026-09-22（第三轮 §3.2 / 第四轮回报） | ✅ | 本侧授权后上游已执行（`--min-value 0`）：覆盖 **36,371 行**、跳过 169 行（无 Bloomberg 返回）、7 行 NULL；`ratio` 由 median 0.750 / 落 1 附近 32.1% → **全部 1.000（100%）**。本侧三项独立验证通过：月均值 202603/202604 = 41.62/43.07（与相邻月 39.46~43.52 对齐）、本侧阈值分桶 33.18%/37.70%/29.11%、suspect 命中 168 行（含批次内 60 行）**与上游预测精确一致**。三层备份可回滚 |
| T20 | 上游 `compute_derived_fields` 的 `log_chg_pct_10s` 用**未分组** `shift(1)` —— 多 ticker 合并输入下每个 ticker 首 bar 与上一个 ticker 末 bar 相除，结果**依赖 chunk 划分（不可复现）** | 上游通知 2026-09-22（第三轮 §四-④）；本侧实测第二十三轮；**上游修复 `b153808` 与答复第二十四轮；回填请求第二十四轮末** | 🔄 **代码已修复（本侧已验证）；已请上游全量回填 194 天，待其执行** | **上游已修复**（`b153808`：按 `(equ_ticker, order_as_of_date)` 分组 + 组内 `mkt_timestamp` 稳定排序取前值 + 读取层显式 `ORDER BY` + 7 例单测；**本侧独立复跑 7 passed**）。§ 根因：**非 schema 问题**，是读取层与计算层的**契约缺陷**（正确性依赖 SQL 返回顺序 / `pd.concat` 拼接顺序 / chunk 划分）。全仓扫描**仅此一处**未分组。§ **回填已决策（2026-09-22 用户定）：选 B 全量 194 天**（不采部分重算 —— 「哪些日期可信」无法自证）；成本 0.5~3 小时、纯本地、无需 Bloomberg、可分批。**验收标准**：`\|x\|>1` 计数应为 **0**、`\|x\|>0.1` 由 11,325 大幅下降、`cum_interval_volatility` 最大值由 37.77 降至 <5、行数保持 6,680,277 不变、其余列取值不应变化；上游须回报自检 + 保留前后快照，**本侧将独立复验**（含抽查首 bar 是否为 0）。§ 护栏：不加代码拦截，**仅文档标注「回填完成前该列存量不可信」**（本侧当前无代码路径读该列）。§ 本侧在回填前**不启用** `cum_interval_volatility` / `standard_cum_interval_volatility`（后者分母为批次全表非零均值，跨批次不可比且会把异常压平） |
| T21 | 前端「评估失败」根因定位与端到端验证 | 本侧实测 2026-09-22（`docs/report-tca-known-limitations.md` 第二十二轮 ⑤⑥） | ✅ | 根因：**两个残留 dev server**（9/15 启的 + 今天 13:58 因 5173 占用改起 5174 的）均未成功监听端口，浏览器连到异常实例。清理 9 个残留进程后单起一个，端到端验证全部通过：`localhost:5173/` → 200；**经前端代理** `POST /api/tca/evaluation/report` → **200**（5,383 字节）；已移除的 `/compare` → **404**；`capabilities.evaluation = true`。**坑**：dev server 监听 `localhost` 在本机只绑 IPv6 `::1`，用 `127.0.0.1` 探测会误判「未启动」。剩余动作：用户在浏览器**硬刷新**以丢弃旧 bundle |
| T18 | 上游重启后首次真实运行，确认批次级守卫未误触发 | 上游通知 2026-09-22（第四/五轮） | ✅ | 上游已完成 **重启**（旧进程 PID 16968/36116 于 9/21 08:18 启动、加载修复前代码 → 重启为 46484/59224）；重启后手动 S7 两日期：`20260428` n=351 中位 34.178 / p90 59.057、`20260429` n=317 中位 34.232 / p90 62.901，远高于拒绝阈值（中位<5 且 p90<10）→ **未触发、放行**，写入行 `<3` 为 **0**，判定**常规运行**。上游另改进为「放行时也记录批次 n/中位/p90」（commit `e5253ad`），今后可持续观测 |



## 已完成

| # | 事项 | 来源 | 状态 | 备注 |
|---|------|------|------|------|
| T14 | CostView 券商算法执行质量评估体系三阶段计划（周度频率 / 分市场 / 控制执行环境变量 / 科学方法） | `docs/archive/2026-09-21/026-costview-algo-eval/plan.md` | ✅ | 2026-09-21 全部交付：计划与阶段一（#68）、阶段二（#69）、阶段三模块与口径（#70）、阶段三收尾（#71）；spec 同日归档。含 ISO 周聚合维度、真实环境变量分层（探测-自给-跨仓三级降级链）、`CostView/src/evaluation/` 推断层与 `POST /api/tca/evaluation/compare`（服务端强制可比性）。K1 费用口径按计划不纳入；未收尾的上游可选项转 T15。**注**：其评估形态（用户选维度 / 基准 / 方法）经用户反馈判定与需求不符，已由 027 重写为综合评估报告 |
| T16 | 评估端点门控降级分支缺自动化用例（`TCA_EVAL_ENABLED=0` 的端点级覆盖） | `docs/archive/2026-09-21/026-costview-algo-eval/checklists/progress.md` Checkpoint 3-C（遗留 026-L3） | ✅ | 2026-09-21 由 027 补齐：`CostView/tests/test_evaluation.py::TestEvaluationEndpoint::test_gate_disabled_is_explicit`（monkeypatch 门控开关 → 断言 `enabled=False` / `sections=None` / 消息含开关名） |
