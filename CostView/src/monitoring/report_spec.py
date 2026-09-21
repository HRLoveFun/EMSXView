"""TCA 报告口径声明（唯一真相源）。

报告脚注、测试断言与聚合器常量全部由此处派生，消除「文档-实现漂移」：
调整口径（加权方式、严重度档位、明细上限、fx 兜底顺序……）只需改本文件，
脚注与一致性校验自动跟随。

纯常量模块，无运行时依赖；不 import 其他 monitoring 模块（避免循环依赖）。
"""

from __future__ import annotations

from typing import Any

#: 口径规范版本号（脚注展示，归档时可追溯口径随版本的演进）
SPEC_VERSION = "2026.09.10"

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
    #: D7 / DP-3 定稿：金额门槛口径 COALESCE(Amount, fill×p_avg)×汇率（Amount 缺失
    #: 不再被误杀）；一致性校验容差 0.5%（仅披露，不改异常表 Amount 展示列）
    "anomaly_notional_gate": "coalesce-amount-fill-pavg",
    "amount_consistency_tolerance_pct": 0.5,
    #: D15 / DP-4 定稿：冲击截断占比分母 = 冲击计算样本（任一冲击指标可计算）
    #: （实现常量见 report_aggregator.IMPACT_TRUNCATED_SHARE_DENOMINATOR，测试断言一致）
    "impact_truncated_share_denominator": "impact_sample",
    #: D17：订单参与率「疑重复记账」临界求和（200%）。唯一实现源见
    #: report_measure.ORDER_PAR_CRITICAL_SUM（异常规则 critical 档 ×100 与探针共用），
    #: 测试断言三处一致（P1-a 复核 F-b 阈值唯一化）
    "order_par_critical_gt": 2.0,
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
    #: 028：波动率量纲统一与披露（实测证据见 docs/archive/2026-09-21/028-volatility-scale-fix/research.md）
    "volatility_unit": "annualized-percent",
    "volatility_scale_cut": 3.0,
    "volatility_scale_fixed_disclosure": "env_coverage.volatility_scale_fixed",
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
        f"异常金额门槛按 {REPORT_SPEC['anomaly_notional_gate']} 口径"
        f"（Amount 缺失回退 fill×p_avg，展示列以 Amount 为准）；"
        f"订单参与率 >{REPORT_SPEC['order_par_critical_gt'] * 100:.0f}% 疑重复记账单独分档；"
        f"冲击截断占比分母为冲击计算样本"
        f"（{REPORT_SPEC['impact_truncated_share_denominator']}）；"
        f"BDIB 缺口金额与 KPI 同源换算并单列未换算金额；"
        f"TCA 整日缺失经差集检测披露；"
        f"成本轴含零轴（pnl_vwap={chart['pnl_vwap']}）、"
        f"参与率与金额轴零锚定（{chart['par_rate']}/{chart['market_notional']}）；"
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
        f"{_granularity_footer_clause()}"
        f"已知限制见 {REPORT_SPEC['known_limitations_doc']}。"
    )
