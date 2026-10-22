"""算法族分类与意图映射契约（057 DL-04）——纯映射数据 + 纯函数，无 IO。

Ownership: platform_data 发布；Consumers: CostView（DL-13 预期成本分组、DL-19/20
同类比较）、ExecutionView（DL-18 意图→算法族）。

口径来源：
- 管道五组（vwap/twap/pov/close/other）：S2 `add_algo_column`（Broker × StrategyType
  精确映射，指南 §5.2）——本契约的 `coarse_group` 保证细分族可映射回五组；
- 精确表种子：tca_route_summary 2026-04-22 至 2026-10-20 全量 96 个
  (Broker, StrategyType, algo) 组合（含 count），近 6 个月 127,569 路由 100% 覆盖；
- 同类比较依据：docs/textbook/Algo_TCA.md:654、:826-832。

已知管道缺口（KNOWN_PIPELINE_GAPS）：本侧细分与管道 algo 的差异集合——管道侧
补映射（POV/SmartMOC/Close 变体）后由 EMSXDataPipeline 实施，DL-06 契约冻结时复核。
"""

from __future__ import annotations

# 映射表版本：结构/规则/数据变更时升版（语义同前两个版本常量）
ALGO_TAXONOMY_VERSION = "algo-taxonomy-v1"

# ── 细分族 ────────────────────────────────────────────────────────────────────
# vwap/twap/pov：管道三组的直接细分；close/auction_close 区分「泛收盘类」
# （Custom 等自定义）与「明确收盘竞价」（MOC/CLOSE/AUCTION 等命名）；
# auction_open：开盘竞价（OnOpen）；is：Implementation Shortfall（当前 0 样本）；
# dma：直接市场接入；liquidity：交叉盘/暗池（CROSSING）；unmapped：未命中显式项。
ALGO_FAMILIES: tuple[str, ...] = (
    "vwap", "twap", "pov",
    "close", "auction_close", "auction_open",
    "is", "dma", "liquidity",
    "other", "unmapped",
)

# 细分族 → 管道五组（可逆约束：每个细分族必须落到五组之一）
FAMILY_TO_COARSE: dict[str, str] = {
    "vwap": "vwap",
    "twap": "twap",
    "pov": "pov",
    "close": "close",
    "auction_close": "close",
    "auction_open": "other",  # 管道无开盘竞价组
    "is": "other",
    "dma": "other",
    "liquidity": "other",
    "other": "other",
    "unmapped": "other",
}

# ── 意图 → 算法族（DL-01 OrderIntent.benchmark 五值） ─────────────────────────
# MIX 拆两段（收盘段 + VWAP 段）；SPECIAL/UNMAPPED 不映射（引擎不出建议，DL-18）。
INTENT_TO_FAMILIES: dict[str, tuple[str, ...]] = {
    "VWAP": ("vwap",),
    "CLOSE": ("auction_close",),
    "MIX": ("auction_close", "vwap"),
    "SPECIAL": (),
    "UNMAPPED": (),
}

# ── 精确表：(broker, strategy_type 归一化) → 细分族 ────────────────────────────
# 种子 = tca_route_summary 全量 96 组合（2026-04-22~2026-10-20，count 见探针记录）。
# 归一化：upper + strip + 去尾点（VWAP. → VWAP）；空/None → ""。
STRATEGY_TYPE_MAP: dict[tuple[str, str], str] = {
    # ── vwap 族 ──
    ("EQ-BARCLAY", "VWAP"): "vwap",
    ("EQ-BARCLAY", "VWAP-EU"): "vwap",
    ("EQ-BNP", "VWAP"): "vwap",
    ("EQ-BOCI", "VWAP"): "vwap",
    ("EQ-CICC", "VWAP"): "vwap",
    ("EQ-CITI", "VWAP"): "vwap",
    ("EQ-CLSA", "VWAP_ADP"): "vwap",
    ("EQ-CLSA-EU", "VWAP_ADP"): "vwap",
    ("EQ-DAIWA", "VWAP"): "vwap",
    ("EQ-HSBC", "VWAP."): "vwap",
    ("EQ-ICBCI", "VWAP"): "vwap",
    ("EQ-INSTNET", "VWAP"): "vwap",
    ("EQ-JPM", "VWAP"): "vwap",
    ("EQ-MACQ", "VWAP"): "vwap",
    ("EQ-MIZUHO", "VWAP"): "vwap",
    ("EQ-ML", "VWAP"): "vwap",
    ("EQ-ML-BR", "VWAP"): "vwap",
    ("EQ-MS", "VWAP"): "vwap",
    ("EQ-NOMURA", "VWAP"): "vwap",
    ("EQ-RBC", "VWAP"): "vwap",
    ("EQ-SCOTIA", "VWAP"): "vwap",
    ("EQ-SEB", "VWAP"): "vwap",
    ("EQ-SG", "VWAP"): "vwap",
    ("EQ-TD", "VWAP"): "vwap",
    ("EQ-UBS", "VWAP"): "vwap",
    ("EQ-WFC", "VWAP"): "vwap",
    ("EQ-ABCI", "VWAP"): "vwap",
    # ── twap 族 ──
    ("EQ-BNP", "TWAP"): "twap",
    ("EQ-CITI", "TWAP"): "twap",
    ("EQ-HSBC", "TWAP."): "twap",
    ("EQ-JPM", "TWAP"): "twap",
    ("EQ-ML", "TWAP"): "twap",
    # ── pov 族（参与率类；命名跨券商高度不一致） ──
    ("EQ-BARCLAY", "WITH-VOL"): "pov",
    ("EQ-BMO", "POV"): "pov",
    ("EQ-BOCI", "POV"): "pov",       # 管道缺口：管道 algo=other
    ("EQ-BNP", "POV"): "pov",
    ("EQ-CICC", "POV"): "pov",       # 管道缺口
    ("EQ-CITI", "PART"): "pov",
    ("EQ-CLSA", "VOLINLINE"): "pov",
    ("EQ-CLSA", "INLN_ADP"): "pov",  # 管道缺口；INLN 与 VolinLine 同源推断
    ("EQ-GS", "PARTCIPTE"): "pov",
    ("EQ-HSBC", "POV."): "pov",
    ("EQ-ICBCI", "POV"): "pov",      # 管道缺口
    ("EQ-INSTNET", "PART"): "pov",
    ("EQ-JPM", "POV"): "pov",
    ("EQ-MACQ", "VOLINLINE"): "pov",
    ("EQ-ML", "POV"): "pov",
    ("EQ-ML-BR", "POV"): "pov",
    ("EQ-MS", "TARGETPOV"): "pov",
    ("EQ-RBC", "POV"): "pov",
    ("EQ-SCOTIA", "POV"): "pov",
    ("EQ-TD", "POV"): "pov",
    ("EQ-UBS", "V-INLINE"): "pov",
    ("EQ-WFC", "POV"): "pov",
    # ── auction_close 族（明确收盘竞价） ──
    ("EQ-BARCLAY", "AUCTIONEU"): "auction_close",
    ("EQ-BARCLAY", "TCLOSE"): "auction_close",
    ("EQ-BMO", "AUCTION"): "auction_close",
    ("EQ-BOCI", "TARGETCLO"): "auction_close",
    ("EQ-BNP", "CLOSE"): "auction_close",  # 管道缺口：管道 algo=other
    ("EQ-BNP", "MOC"): "auction_close",
    ("EQ-CITI", "MOC"): "auction_close",
    ("EQ-CITI", "CLOSE"): "auction_close",
    ("EQ-CICC", "CLOSETGT"): "auction_close",
    ("EQ-CLSA", "MOC_ADP"): "auction_close",
    ("EQ-CLSA-EU", "MOC_ADP"): "auction_close",
    ("EQ-DAIWA", "CLOSE"): "auction_close",
    ("EQ-GS", "AUCTION"): "auction_close",
    ("EQ-HSBC", "HSBCCLOSE"): "auction_close",
    ("EQ-ICBCI", "CLOSE"): "auction_close",
    ("EQ-INSTNET", "AUCTION"): "auction_close",
    ("EQ-INSTNET", "TARGETCL"): "auction_close",
    ("EQ-JPM", "CLOSE"): "auction_close",
    ("EQ-MACQ", "CLOSEPLUS"): "auction_close",
    ("EQ-MIZUHO", "TGTCLOSE"): "auction_close",
    ("EQ-ML", "QMOC"): "auction_close",
    ("EQ-ML", "QMOC_APEU"): "auction_close",
    ("EQ-ML-BR", "QMOC"): "auction_close",
    ("EQ-MS", "CLOSE"): "auction_close",
    ("EQ-NOMURA", "TARGETCLS"): "auction_close",
    ("EQ-RBC", "CLOSER"): "auction_close",
    ("EQ-SCOTIA", "MOCDIRECT"): "auction_close",
    ("EQ-SCOTIA", "SMRTCLOSE"): "auction_close",
    ("EQ-SEB", "TGTCLOSE"): "auction_close",
    ("EQ-SG", "SMARTMOC"): "auction_close",  # 管道缺口：管道 algo=other
    ("EQ-TD", "CLOSE"): "auction_close",
    ("EQ-UBS", "AT CLOSE"): "auction_close",
    ("EQ-UBS", "CUSTOM2"): "close",   # 自定义（管道归 close，语义非明确竞价）
    ("EQ-WFC", "CLOSE"): "auction_close",
    # ── close 族（泛收盘类：管道归 close 但命名非竞价语义） ──
    ("EQ-NOMURA", "CUSTOM"): "close",
    # ── auction_open 族 ──
    ("EQ-BMO", "ONOPEN"): "auction_open",  # 管道缺口：管道无开盘竞价组（other）
    # ── liquidity 族（交叉盘） ──
    ("CROSSING", ""): "liquidity",         # StrategyType 空/None，Broker=CROSSING
}

# ── 兜底规则（有序，contains 匹配归一化后的 StrategyType） ─────────────────────
# 精确表未命中时按顺序尝试；均未命中 → unmapped（显式，不静默归 other）。
STRATEGY_TYPE_RULES: tuple[tuple[str, str], ...] = (
    ("VWAP", "vwap"),
    ("TWAP", "twap"),
    ("POV", "pov"),
    ("PART", "pov"),
    ("VOLINLINE", "pov"),
    ("WITH-VOL", "pov"),
    ("INLINE", "pov"),
    ("MOC", "auction_close"),
    ("CLOSE", "auction_close"),
    ("AUCTION", "auction_close"),
    ("ONOPEN", "auction_open"),
    ("SHORTFALL", "is"),
    ("ARRIVAL", "is"),
    ("DMA", "dma"),
    ("DIRECT", "dma"),
    ("LIQ", "liquidity"),
    ("DARK", "liquidity"),
    ("CROSS", "liquidity"),
)

# ── 已知管道缺口：本侧 coarse ≠ 管道 algo 的组合（交管道侧补映射） ──────────────
# key 与 STRATEGY_TYPE_MAP 相同；value = (本侧 coarse, 管道 algo, 说明)。
KNOWN_PIPELINE_GAPS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("EQ-BOCI", "POV"): ("pov", "other", "管道 mapping 未含 BOCI 的 POV"),
    ("EQ-CICC", "POV"): ("pov", "other", "管道 mapping 未含 CICC 的 POV"),
    ("EQ-ICBCI", "POV"): ("pov", "other", "管道 mapping 未含 ICBCI 的 POV"),
    ("EQ-SG", "SMARTMOC"): ("close", "other", "SmartMOC 收盘类命名管道未映射"),
    ("EQ-BNP", "CLOSE"): ("close", "other", "BNP 的 Close 变体管道未映射"),
    ("EQ-CLSA", "INLN_ADP"): ("pov", "other", "INLN 推断为 VolinLine 同源（参与率），管道未映射"),
}


def normalize_strategy_type(strategy_type: str | None) -> str:
    """归一化 StrategyType：upper + strip + 去尾点（VWAP. → VWAP）。空/None → ''。"""
    text = (strategy_type or "").strip().upper()
    return text.rstrip(".") if text.endswith(".") else text


def classify_algo(broker: str, strategy_type: str | None) -> str:
    """(broker, strategy_type) → 细分族：精确表 → 兜底规则 → unmapped。"""
    key = ((broker or "").strip().upper(), normalize_strategy_type(strategy_type))
    family = STRATEGY_TYPE_MAP.get(key)
    if family is not None:
        return family
    normalized = key[1]
    for keyword, rule_family in STRATEGY_TYPE_RULES:
        if keyword in normalized:
            return rule_family
    return "unmapped"


def coarse_group(family: str) -> str:
    """细分族 → 管道五组（vwap/twap/pov/close/other）。未知族 → other。"""
    return FAMILY_TO_COARSE.get(family, "other")


def intent_families(benchmark: str) -> tuple[str, ...]:
    """意图（DL-01 benchmark 五值）→ 算法族列表；MIX 拆两段。"""
    return INTENT_TO_FAMILIES.get(benchmark, ())


def coverage_of(rows: list[tuple[str, str | None, int]]) -> dict:
    """覆盖率统计：rows = [(broker, strategy_type, count)]（预聚合）。

    返回 {total, covered, unmapped, coverage_pct, unmapped_list, gap_counts}：
    - covered = 细分族命中（非 unmapped）的路由数；
    - unmapped_list = [(broker, strategy, count)] 明细（供 UNMAPPED 报告）；
    - gap_counts = 命中已知管道缺口的 (broker, strategy) → count（已知差异不扣覆盖）。
    """
    total = 0
    covered = 0
    unmapped_list: list[tuple[str, str, int]] = []
    gap_counts: dict[tuple[str, str], int] = {}
    for broker, strategy_type, count in rows:
        total += count
        family = classify_algo(broker, strategy_type)
        key = ((broker or "").strip().upper(), normalize_strategy_type(strategy_type))
        if family == "unmapped":
            unmapped_list.append(((broker or "").strip().upper(), normalize_strategy_type(strategy_type), count))
        else:
            covered += count
        if key in KNOWN_PIPELINE_GAPS:
            gap_counts[key] = gap_counts.get(key, 0) + count
    return {
        "total": total,
        "covered": covered,
        "unmapped": total - covered,
        "coverage_pct": round(covered / total * 100, 4) if total else 0.0,
        "unmapped_list": unmapped_list,
        "gap_counts": gap_counts,
    }
