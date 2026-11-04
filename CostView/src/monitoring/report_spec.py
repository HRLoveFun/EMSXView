"""TCA 报告口径声明（唯一真相源）。

报告脚注、测试断言与聚合器常量全部由此处派生，消除「文档-实现漂移」：
调整口径（加权方式、严重度档位、明细上限、fx 兜底顺序……）只需改本文件，
脚注与一致性校验自动跟随。

纯常量模块，无运行时依赖；不 import 其他 monitoring 模块（避免循环依赖）。
"""

from __future__ import annotations

from typing import Any

from . import report_measure as rm

#: 口径规范版本号（脚注展示，归档时可追溯口径随版本的演进）
#: 2026.11.03：F1 —— Amount 语义纠正（委托股数，非金额），异常金额列与门槛改用
#: fill×p_avg；删除 amount_consistency 探针与其容差声明
#: 2026.11.03b：F2 —— 订单参与率不再按组内求和判定（单路由看自身、多路由看组内
#: 最大路由参与率），规则拆为 order_par_single_gt100 / route_par_extreme
#: 2026.11.04：210 §4.12 —— 报告头之后新增全局可信度横幅（四类检查始终渲染，
#: 未检查明示）；数量矛盾改按订单级 ΣAmount 与 ΣRouteShares（股数 vs 股数）判定
#: 2026.11.04b：210 §3.6.2 —— KPI 之后新增交易员执行摘要，执行方排行随之前移
SPEC_VERSION = "2026.11.04b"

#: 报告口径声明
REPORT_SPEC: dict[str, Any] = {
    "spec_version": SPEC_VERSION,
    #: 唯一加权口径：成交额加权（fill × p_avg），与总成交金额同源
    "weight_mode": "traded",
    "weight_expression": "fill * p_avg",
    #: 加权均值的覆盖披露：样本（条数）覆盖与权重（成交额）覆盖低于阈值时标注结论仅供参考
    #: （实现常量见 report_measure.SAMPLE_COVERAGE_MIN_PCT，由测试断言两者一致）
    "weight_coverage_min_pct": 90.0,
    #: 报告作用域：默认 BDIB 白名单内全量，用户指定 exchange 时为用户口径（全报告小节统一）
    "scope_modes": ("bdib_whitelist", "user_exchange_filter"),
    "scope_whitelist_source": "Config.BDIB_EXCHANGE",
    #: 未成交金额的价格回退链（p_avg 缺失时依次回退；全部缺失则该路由不计入并披露条数）
    "unfilled_price_fallbacks": ("p_avg", "p_arrival", "p_decision", "p_close"),
    #: 异常明细下限门槛（笔数 / 金额）的豁免项：严重未完成必须可见（结构化绑定规则与档位，
    #: 实现常量见 report_measure.FLOOR_EXEMPT_RULE / FLOOR_EXEMPT_SEVERITY，由测试断言一致）
    "anomaly_floor_exempt": {"rule": "fill_pct", "severity": "critical"},
    #: 异常严重度档位（warning 决定是否入清单，critical 用于分级标注）
    "anomaly_severity_levels": ("warning", "critical"),
    #: HTML 明细渲染上限（全量经导出 CSV 获取）
    "anomaly_row_limit": 1000,
    #: fx 兜底顺序：fill_bdib 回填 → tca.fx_rate → USD 按 1.0
    "fx_fallback": ("fill_bdib_backfill", "tca.fx_rate", "1.0-usd"),
    #: BDIB 缺口金额换算与 KPI 同源（fill_bdib 回填 + 小计价单位修正 + 逐行换算，
    #: 未能换算的本币金额单独披露为 missing_notional_unconvertible）
    "gap_notional_fx": "same-as-kpi-with-unconvertible-disclosure",
    #: TCA 整日缺失检测：健康扫描输出 tca_gap_dates（有成交但无 TCA 汇总的日期），
    #: 报告头数据质量区披露，覆盖率表橙底行高亮
    "tca_gap_detection": True,
    #: SLA 分母对 bdib_missing 类指标剔除「BDIB 缺口路由」
    #: （实现见 metric_coverage.SLA_DENOMINATOR_BY_REASON，由测试断言一致）
    "sla_bdib_missing_denominator": "non_bdib_gap",
    #: 机会成本公式（下游消费者据此解读 opportunity_cost 列）
    "opportunity_cost_formula": "(Pn - P0) * unfilled * side",
    #: 明确排除的成本/口径项
    "excluded": (
        "explicit_fees", "rebates", "taxes", "L2_liquidity", "pre_trade_forecast",
    ),
    #: D4 / DP-1 定稿口径 B：排行双维门槛（组样本量 + 组成交额占比）与双侧输出
    #: （实现常量见 report_aggregator._RANKING_MIN_SAMPLE 等，由测试断言一致）
    "ranking_min_sample": 5,
    "ranking_min_notional_share": 0.001,
    "ranking_sides": ("best", "worst"),
    #: D5 / DP-2 定稿：PWP 纳入成交额加权体系（WEIGHTED_METRICS），默认聚合曲线
    #: + Top N 市场小多图（跨市场混合的逐档值无物理解释，分市场解释由小图承接）
    "pwp_weight_mode": "traded",
    "pwp_by_exchange_top_markets": 6,
    #: F1（2026-11-03）：异常金额门槛与展示均为成交金额 fill×p_avg×汇率；零成交路由
    #: 按 RouteShares×p_avg×汇率 计（严重未完成另享 fill_pct critical 豁免）。
    #: 原口径 COALESCE(Amount, fill×p_avg) 把委托股数当金额（实测 82.55% 路由
    #: Amount == RouteShares），US 近 30 天 82.8% 的路由被金额门槛误剔除。
    "anomaly_notional_gate": "fill-times-pavg-fx",
    #: F1：Amount 列的语义 —— 委托股数（非金额），必须单独按数量列展示，
    #: 不得渲染为货币、不得作为金额门槛（实现见 anomaly_query.AnomalyRoute.amount_shares）
    "amount_column_semantics": "委托股数（非金额）",
    #: D15 / DP-4 定稿：冲击截断占比分母 = 冲击计算样本（任一冲击指标可计算）
    #: （实现常量见 report_aggregator.IMPACT_TRUNCATED_SHARE_DENOMINATOR，测试断言一致）
    "impact_truncated_share_denominator": "impact_sample",
    #: F2（2026-11-03）：订单参与率不再以组内求和判定 —— 单路由组看自身参与率，
    #: 多路由组看组内最大路由参与率（各路由共享同一市场成交量分母，求和不可加总）。
    #: 唯一实现源见 report_measure.ORDER_PAR_SUSPECT_RATE / ORDER_PAR_CRITICAL_RATE，
    #: 测试断言声明层与规则默认值一致。
    "order_par_suspect_rate": rm.ORDER_PAR_SUSPECT_RATE,
    "order_par_critical_rate": rm.ORDER_PAR_CRITICAL_RATE,
    "order_par_multi_route_rule": "max-route-rate",
    #: 210 §4.12：订单级「数量矛盾」容差 —— ΣAmount 与 ΣRouteShares 的偏差上限
    #: （股数 vs 股数，与成交金额无关；F1 已确认 Amount 是委托股数）。
    #: 实现常量见 report_measure.ORDER_AMOUNT_QTY_TOLERANCE，测试断言两处一致。
    "amount_qty_tolerance": rm.ORDER_AMOUNT_QTY_TOLERANCE,
    #: 210 §4.12：全局可信度横幅的四类检查（顺序即展示顺序）与其影响 KPI，
    #: 由 report_measure.CREDIBILITY_CHECKS 派生；横幅始终渲染（含 0 触发与空数据）。
    "credibility_checks": tuple(
        {"id": c.id, "unit": c.unit, "affected_kpis": c.affected_kpis}
        for c in rm.CREDIBILITY_CHECKS
    ),
    "credibility_always_rendered": True,
    #: 第四类（逐笔质量）在报告层的固定状态：未检查（跨库逐笔聚合超横幅预算），
    #: 逐笔口径由 CostView → Trader Review 当前页承载；不得写成「通过」。
    "credibility_fill_quality": "not-checked-report-layer",
    #: 210 §3.6.2：交易员执行摘要（按订单数 Top N，附未列出交易员数）。
    #: 实现常量见 trader_query.TRADER_SUMMARY_LIMIT / LOW_COMPLETION_THRESHOLD，
    #: 测试断言两处一致（声明层不 import 交易员域，避免口径模块反向依赖）。
    "trader_summary_limit": 10,
    "trader_low_completion_threshold": 0.8,
    #: 交易员归属取成交股数最大路由；异常订单按**路由**归属交易员
    #: （跨交易员订单会分别计入，故各交易员异常数之和可能略大于去重订单数）
    "trader_summary_attribution": "dominant-route",
    "trader_anomaly_attribution": "route-level-per-trader",
    #: D1 / DP-5 定稿：图表轴锚定硬规则（防渲染器各图各自发挥；护栏测试断言
    #: SVG 产物存在零轴元素）
    "chart_axis": {
        "pnl_vwap": "symmetric-around-zero",
        "par_rate": "zero-anchored",
        "market_notional": "zero-anchored",
        "ticks_per_axis": 5,
    },
    #: 已知限制清单文档（脚注引用，便于归档追溯）
    "known_limitations_doc": "docs/report-tca-known-limitations.md",
    #: 026：聚合粒度与期间键（day 默认 = 既有按日产出逐字节不变；week 为 ISO 8601
    #: 周键，跨年周按「当周周四所在年份」归属；month 为自然月）。实现单点见
    #: report_measure.GRANULARITIES / DEFAULT_GRANULARITY / period_key_expr，
    #: 由测试断言一致；受影响小节为走势 / 分市场金额趋势 / 指标覆盖率。
    "granularities": ("day", "week", "month"),
    "default_granularity": "day",
    "week_key_mode": "iso-8601-weekday-monday",
    #: 期间序列不补零（延续既有「仅含有数据交易日」约定），仅披露覆盖期间数
    "period_series_no_fill": True,
    #: 026 阶段二：环境 cohort 的**真实字段来源**（实现单点见 monitoring.env_context，
    #: 分桶分支见 tca_utils.cohort_key_and_label；由测试断言与 ENV_DIMENSIONS 一致）
    "env_cohort_sources": {
        "time_of_day": "fill_bdib.mkt_timestamp（路由内最早成交时刻）",
        "liquidity_adv20": "fill / bdib_daily_summary.adv_20d",
        # 028：该列实为**年化百分比**（反推公式 = std(日对数收益率) × √252 × 100，
        # 实测中位 26.075）；202603/202604 区间被上游写成**年化小数**，数据入口统一归一化
        "volatility": "bdib_daily_summary.daily_volatility（年化百分比）",
    },
    #: 028b：波动率量纲**监测**（只检测不修改）—— 上游已确认权威定义并修复根因；
    #: 证据见 docs/archive/2026-09-21/028-volatility-scale-fix/research.md
    "volatility_unit": "annualized-percent",
    "volatility_source": "Bloomberg VOLATILITY_30D（30 交易日年化历史波动率，百分比单位）",
    "volatility_scale_cut": 3.0,
    "volatility_scale_suspect_disclosure": "env_coverage.volatility_scale_suspect",
    #: 026 阶段二：环境字段不可得时**回退的既有代理口径**（L3 降级；不可得必须是可见事实）
    "env_cohort_fallbacks": {
        "time_of_day": "unknown",
        "liquidity_adv20": "par_rate",
        "volatility": "abs(pnl_vwap)",
    },
    #: 026 阶段二：环境变量可得率随 scorecard payload 披露（filters.env_coverage）
    "env_coverage_disclosure": "scorecard.filters.env_coverage",
    #: 027：综合评估报告口径（实现见 `CostView/src/evaluation/`；本模块不 import 它，
    #: 避免 `evaluation → monitoring.env_context → monitoring/__init__ → report_spec` 的包级
    #: 循环，故此处写字面量并由 `tests/test_evaluation.py` 断言与实现常量一致）
    "evaluation": {
        # 控制维度（分层键）：全部来自阶段二真实环境变量；禁止用成本量（循环论证）。
        # **不含 asset_class**：与 Exchange 高度共线，纳入只使层更稀疏而无控制力增益。
        "strata_dimensions": (
            "Exchange", "time_of_day", "liquidity_adv20", "volatility",
        ),
        # 027：控制维度与分组维度**正交** —— 按某维度分组时分层键自动排除该维度。
        # （否则层内该维度取值恒定、分层退化为 1 层；实测曾使三个环境维度全部退化）
        "strata_excludes_grouping_dimension": True,
        # 构成失衡（TVD）为**描述性提示**，不再作为「不可比即拒绝」的门禁（027 修正；
        # 026 的整体分布门禁在真实数据上恒为拒绝 —— Exchange TVD 恒等于 1.0）
        "imbalance_metric": "total-variation-distance",
        "imbalance_alert_threshold": 0.2,
        "imbalance_blocks_output": False,
        # 检验方法：三种方法回答不同问题，不得只报最有利者（D1 同源要求）—— 全部并列
        "methods": ("t-test", "ks", "chi2"),
        # 可信区间用 bootstrap：成本分布右偏厚尾，正态近似会系统性窄化区间。
        # 每对样本只算一次（与检验方法无关）；重采样次数按报告可接受耗时取值
        "ci_method": "bootstrap-percentile",
        "ci_bootstrap": 200,
        # 多重比较校正：同一维度内对多个分组各做一次检验，必须校正
        "multiple_comparison": "benjamini-hochberg",
        # 027：比较形态为「每组 vs 其余（层内加权合并）」，而非 C(n,2) 全组合枚举
        "comparison_shape": "group-vs-rest-stratified",
        # 基准**全部并列**（决策基准 + 市场时间基准 + 收盘 + IS 分解），检验固定在主基准；
        # 不再由用户选择（026 的 benchmark_required 语义随之废弃）
        "benchmarks": ("arrival", "vwap", "close", "is"),
        "primary_benchmark": "arrival",
        # 027：无「不可比」终止态 —— 结论照出，可信度以 confidence / coverage 披露
        "comparability_enforced_server_side": False,
        "confidence_disclosed": True,
    },
}

#: 排除项的中文展示文案（与 REPORT_SPEC["excluded"] 语义一一对应）
EXCLUDED_TEXT = "不含显性费用/返佣/税费；无 L2 订单簿流动性；不含事前预测"


def _p0_p1_footer_clauses() -> str:
    """P0 / P1-a / P1-b 新增口径的脚注子句（全由 SPEC 绑定常量插值，不手写数值）。

    F-c（第八轮复核）：离线归档 HTML 的口径自证载体是脚注 —— 新增声明若只进
    SPEC 与台账而不进脚注，归档读者只能凭版本号回查，声明侧开始漂移。
    """
    share_pct = REPORT_SPEC["ranking_min_notional_share"] * 100
    chart = REPORT_SPEC["chart_axis"]
    return (
        f"排行按双维门槛（组样本 n≥{REPORT_SPEC['ranking_min_sample']} 且"
        f"组成交额占比≥{share_pct:.1f}%）输出最优/最差双侧 Top10；"
        f"PWP 五档为成交额加权（pwp_weight_mode={REPORT_SPEC['pwp_weight_mode']}）"
        f"并披露覆盖、分市场小图（Top {REPORT_SPEC['pwp_by_exchange_top_markets']}）"
        f"承接解释；"
        f"异常金额列与门槛均为成交金额 fill×p_avg×汇率"
        f"（{REPORT_SPEC['anomaly_notional_gate']}；零成交路由按委托股数×p_avg×汇率 计）；"
        f"Amount 为{REPORT_SPEC['amount_column_semantics']}，不作金额使用；"
        f"订单参与率按分组判定：单路由 >"
        f"{REPORT_SPEC['order_par_suspect_rate'] * 100:.0f}% 标 par_suspect"
        f"（>{REPORT_SPEC['order_par_critical_rate'] * 100:.0f}% critical），"
        f"多路由取组内最大路由参与率、不求和"
        f"（{REPORT_SPEC['order_par_multi_route_rule']}）；"
        f"冲击截断占比分母为冲击计算样本"
        f"（{REPORT_SPEC['impact_truncated_share_denominator']}）；"
        f"BDIB 缺口金额与 KPI 同源换算并单列未换算金额；"
        f"TCA 整日缺失经差集检测披露；"
        f"成本轴含零轴（pnl_vwap={chart['pnl_vwap']}）、"
        f"参与率与金额轴零锚定（{chart['par_rate']}/{chart['market_notional']}）；"
    )


def _credibility_footer_clause() -> str:
    """210 §4.12：可信度横幅的口径自证（检查类数、数量矛盾容差、未检查项）。

    归档 HTML 的读者只能凭脚注判断「横幅里那个 0 是没问题还是没检查」，故三类
    事实必须进脚注：检查类数、数量矛盾的判定界、未检查项不记作通过。检查项名称
    只在横幅与 ``credibility_checks`` 声明里出现一次，脚注不复制（防两处漂移）。
    """
    tolerance_pct = REPORT_SPEC["amount_qty_tolerance"] * 100
    render_mode = (
        "0 触发也渲染" if REPORT_SPEC["credibility_always_rendered"] else "仅触发时渲染"
    )
    return (
        f"报告头可信度横幅按 {len(REPORT_SPEC['credibility_checks'])} 类检查披露"
        f"（{render_mode}），0 触发不等于数据无缺陷、未检查项明示而不记作通过；"
        f"数量矛盾按订单级 ΣAmount 与 ΣRouteShares 偏差 >{tolerance_pct:.1f}% 判定"
        f"（股数口径，非金额）；"
    )


def _trader_summary_footer_clause() -> str:
    """210 §3.6.2：交易员执行摘要的口径自证（行数、完成率界、归属与异常归集）。

    归档读者看到表里某交易员「异常订单 0」时，必须能分辨这是「确实没有」还是
    「按路由归属后该交易员没有命中」；跨交易员订单会分别计入，这一条必须写明。
    """
    threshold_pct = REPORT_SPEC["trader_low_completion_threshold"] * 100
    return (
        f"交易员执行摘要按订单数取前 {REPORT_SPEC['trader_summary_limit']} 名，"
        f"完成率界 {threshold_pct:.0f}%、加权 arrival 为成交额加权"
        f"（权重 fill × p_avg）；交易员归属取 {REPORT_SPEC['trader_summary_attribution']}"
        f"（成交股数最大路由），异常订单按 {REPORT_SPEC['trader_anomaly_attribution']} "
        f"归集（跨交易员订单分别计入）；本报告不随附交易员 CSV，"
        f"订单级明细见 CostView → Trader Review；"
    )


def _granularity_footer_clause() -> str:
    """026 新增：聚合粒度与期间键声明（由 SPEC 常量插值，不手写数值）。

    归档 HTML 的口径自证载体是脚注 —— 粒度改变了走势与分市场趋势的横轴语义，
    不写进脚注则归档读者无法判断「2026-W01 是周还是日」。
    """
    granularities = "/".join(REPORT_SPEC["granularities"])
    no_fill = "不补零" if REPORT_SPEC["period_series_no_fill"] else "补零"
    return (
        f"聚合粒度可选 {granularities}"
        f"（默认 {REPORT_SPEC['default_granularity']}）；"
        f"周键为 {REPORT_SPEC['week_key_mode']}，跨年周按 ISO 周年份归属；"
        f"期间序列{no_fill}，仅披露覆盖期间数；"
    )


def footer_text() -> str:
    """由口径常量生成报告脚注（含版本号与已知限制文档引用）。"""
    fallbacks = " → ".join(REPORT_SPEC["unfilled_price_fallbacks"])
    return (
        f"口径 v{REPORT_SPEC['spec_version']}：价格偏离（{EXCLUDED_TEXT}）；"
        f"opportunity_cost 按 {REPORT_SPEC['opportunity_cost_formula']} 计；"
        f"加权口径为 {REPORT_SPEC['weight_expression']}（与总成交金额同源），"
        f"并披露样本量与权重覆盖率（低于 "
        f"{REPORT_SPEC['weight_coverage_min_pct']:.0f}% 标注结论仅供参考）；"
        f"统计范围默认 BDIB 白名单"
        f"（{REPORT_SPEC['scope_whitelist_source']}）内全量、全报告小节同口径；"
        f"未成交金额按 {fallbacks} 回退计价，零成交路由计入并单列；"
        f"异常严重度分 "
        f"{len(REPORT_SPEC['anomaly_severity_levels'])} 档，明细上限 "
        f"{REPORT_SPEC['anomaly_row_limit']} 条（全量见随附导出 CSV）；"
        f"{_p0_p1_footer_clauses()}"
        f"{_credibility_footer_clause()}"
        f"{_trader_summary_footer_clause()}"
        f"{_granularity_footer_clause()}"
        f"已知限制见 {REPORT_SPEC['known_limitations_doc']}。"
    )
