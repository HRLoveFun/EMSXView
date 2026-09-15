"""TCA 报告口径声明（唯一真相源）。

报告脚注、测试断言与聚合器常量全部由此处派生，消除「文档-实现漂移」：
调整口径（加权方式、严重度档位、明细上限、fx 兜底顺序……）只需改本文件，
脚注与一致性校验自动跟随。

纯常量模块，无运行时依赖；不 import 其他 monitoring 模块（避免循环依赖）。
"""

from __future__ import annotations

from typing import Any

#: 口径规范版本号（脚注展示，归档时可追溯口径随版本的演进）
SPEC_VERSION = "2026.09.2"

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
    #: 机会成本公式（下游消费者据此解读 opportunity_cost 列）
    "opportunity_cost_formula": "(Pn - P0) * unfilled * side",
    #: 明确排除的成本/口径项
    "excluded": (
        "explicit_fees", "rebates", "taxes", "L2_liquidity", "pre_trade_forecast",
    ),
    #: 已知限制清单文档（脚注引用，便于归档追溯）
    "known_limitations_doc": "docs/report-tca-known-limitations.md",
}

#: 排除项的中文展示文案（与 REPORT_SPEC["excluded"] 语义一一对应）
EXCLUDED_TEXT = "不含显性费用/返佣/税费；无 L2 订单簿流动性；不含事前预测"


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
        f"已知限制见 {REPORT_SPEC['known_limitations_doc']}。"
    )
