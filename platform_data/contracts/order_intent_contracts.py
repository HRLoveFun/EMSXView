"""订单意图与 EMSX 导出行契约（057 DL-01）。

Ownership: MarketView 发布（EMSX 手工导出解析）；Consumers: ExecutionView
（handoff v2，DL-14）、CostView（评估口径，DL-19）。
纯 dataclass，无业务逻辑、无 IO。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# PM Note 13 意图映射表版本：映射规则变更时升版，随每条意图透出，
# 供 DL-07 管道侧对齐与事后按版本归类（DL-19）。
INTENT_MAPPING_VERSION = "emsx-pm-note-v1"

# 意图来源标识：v0 唯一来源为 EMSX 手工导出（D-1）；DL-07 入库后
# 新增管道来源时按同款常量扩展，历史数据按 intent_source 区分。
INTENT_SOURCE_EMSX_EXPORT = "emsx-export"

# OrderIntent.benchmark 取值集合（供消费侧校验与文档对齐）
INTENT_BENCHMARKS = ("VWAP", "CLOSE", "MIX", "SPECIAL", "UNMAPPED")


@dataclass(frozen=True)
class OrderIntent:
    """PM Note 13 解析出的订单意图。

    order_key：PM Note 的 `^` 段连接键（含首个 `^`，如 `^1234567^0`），
        与订单级字段 notes（EMSX_NOTES）匹配；缺失时为空串。
    benchmark：VWAP | CLOSE | MIX | SPECIAL | UNMAPPED。
    close_pct：收盘参与比例（CLOSE=100.0，MIX=导出值）；非收盘意图为 None。
    raw_note：PM Note 13 原文，保留备查。
    unmatched_reason：未匹配原因码（empty_pm_note / unknown_prefix /
        missing_order_key）；可匹配时为 None——非 None 即进未匹配清单。
    valid_from / export_ts：该版本意图的生效时间 / 所属导出快照时间；
        v0 两者同值，DL-07 按导出时间留版本时分离。
    """

    order_key: str
    benchmark: str
    close_pct: float | None
    raw_note: str
    intent_source: str
    valid_from: str
    export_ts: str
    unmatched_reason: str | None = None


@dataclass(frozen=True)
class UnmatchedOrder:
    """未匹配清单条目：意图不可映射，或可映射但缺连接键。"""

    code: str
    pm_note: str
    reason: str


@dataclass(frozen=True)
class BlotterOrderRow:
    """EMSX 导出一行（盘前单 v0 展示字段）。

    关键列类型化；其余导出列清洗后原样进 extra_fields（遮蔽值/受限值
    已按缺失剔除），供盘前单展示与后续 DL 复用，不承担计算。
    """

    code: str
    exch_code: str
    name: str
    side: str
    qty: float | None
    ccy: str
    status: str
    fill_qty: float | None
    pct_filled: float | None
    q_pct_5d_adv: float | None
    q_pct_tdy: float | None
    rem_bal_pct_avg_cls_auct_vol: float | None
    working_val_usd: float | None
    value_usd: float | None
    chg_pct_dtdy: float | None
    last_px_vs_vwap_bps: float | None
    earn_rpt_time: str | None
    ex_dvd_flag: str | None
    brkr_code: str
    create_time: str
    pm_note: str
    intent: OrderIntent
    extra_fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PreTradeOrderBoard:
    """盘前单 v0：最新一份导出的解析结果。

    intent_coverage_pct：有意向且带连接键的订单占比（0–100）。
    unmatched：未匹配清单（意图不可映射或缺连接键），盘中人工补登入口。
    """

    exported_at: str
    export_file_name: str
    order_count: int
    intent_coverage_pct: float
    orders: list[BlotterOrderRow]
    unmatched: list[UnmatchedOrder]
    intent_mapping_version: str = INTENT_MAPPING_VERSION
