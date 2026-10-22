"""057 DL-04 — 算法族分类与意图映射测试。

锁死行为（tasks.md DL-04 检验方法）：
1. 精确表命中（组合与族来自真实 96 组合分布）；
2. 归一化（VWAP.→VWAP、Close↔close、None/'' 不抛错）；
3. 兜底规则（新 broker 命名 → 族）；
4. coarse_group 全枚举（每个细分族都映射回五组之一）；
5. 意图 → 族（五值，MIX 拆两段）；
6. KNOWN_PIPELINE_GAPS 一致性（差异 ⊆ 已知缺口；非缺口组合 coarse 必须等于管道 algo）；
7. coverage_of 统计与阈值。
"""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    ALGO_FAMILIES,
    ALGO_TAXONOMY_VERSION,
    FAMILY_TO_COARSE,
    INTENT_TO_FAMILIES,
    KNOWN_PIPELINE_GAPS,
    STRATEGY_TYPE_MAP,
    classify_algo,
    coarse_group,
    coverage_of,
    intent_families,
    normalize_strategy_type,
)


class TestExactMap:
    """用例 1：精确表命中。"""

    def test_close_auction_family(self):
        assert classify_algo("EQ-MS", "CLOSE") == "auction_close"
        assert classify_algo("EQ-GS", "AUCTION") == "auction_close"
        assert classify_algo("EQ-BARCLAY", "AuctionEU") == "auction_close"
        assert classify_algo("EQ-BNP", "MOC") == "auction_close"
        assert classify_algo("EQ-ML", "QMOC_APEU") == "auction_close"
        assert classify_algo("EQ-UBS", "AT CLOSE") == "auction_close"
        assert classify_algo("EQ-SG", "SmartMOC") == "auction_close"  # 已知缺口组合

    def test_generic_close_family(self):
        # 管道归 close 但命名非竞价语义 → close 族
        assert classify_algo("EQ-NOMURA", "Custom") == "close"
        assert classify_algo("EQ-UBS", "CUSTOM2") == "close"

    def test_vwap_twap_pov_families(self):
        assert classify_algo("EQ-BARCLAY", "VWAP-EU") == "vwap"
        assert classify_algo("EQ-HSBC", "VWAP.") == "vwap"
        assert classify_algo("EQ-JPM", "TWAP") == "twap"
        assert classify_algo("EQ-HSBC", "POV.") == "pov"
        assert classify_algo("EQ-GS", "PARTCIPTE") == "pov"
        assert classify_algo("EQ-BARCLAY", "With-Vol") == "pov"
        assert classify_algo("EQ-UBS", "V-INLINE") == "pov"

    def test_liquidity_and_open_auction(self):
        assert classify_algo("CROSSING", None) == "liquidity"
        assert classify_algo("CROSSING", "") == "liquidity"
        assert classify_algo("EQ-BMO", "OnOpen") == "auction_open"

    def test_known_gap_combos_are_mapped(self):
        for key in KNOWN_PIPELINE_GAPS:
            assert classify_algo(*key) != "unmapped", key


class TestNormalization:
    """用例 2：归一化。"""

    def test_normalize_rules(self):
        assert normalize_strategy_type("VWAP.") == "VWAP"
        assert normalize_strategy_type(" Close ") == "CLOSE"
        assert normalize_strategy_type(None) == ""
        assert normalize_strategy_type("") == ""

    def test_none_and_empty_do_not_raise(self):
        assert classify_algo("EQ-X", None) == "unmapped"
        assert classify_algo("", "") == "unmapped"


class TestFallbackRules:
    """用例 3：兜底规则（新 broker 命名）。"""

    def test_rule_hits(self):
        assert classify_algo("EQ-NEW", "SMARTVWAP") == "vwap"
        assert classify_algo("EQ-NEW", "TARGET_MOC") == "auction_close"
        assert classify_algo("EQ-NEW", "ONOPEN") == "auction_open"
        assert classify_algo("EQ-NEW", "LIQ_SWEEP") == "liquidity"
        assert classify_algo("EQ-NEW", "ARRIVAL_PX") == "is"
        assert classify_algo("EQ-NEW", "DMA_DIRECT") == "dma"

    def test_rule_miss_is_unmapped(self):
        assert classify_algo("EQ-NEW", "MYSTERY") == "unmapped"

    def test_exact_map_wins_over_rule(self):
        # 精确表优先于规则（CUSTOM2 规则未覆盖，精确表命中 close）
        assert classify_algo("EQ-UBS", "CUSTOM2") == "close"


class TestCoarseGroup:
    """用例 4：细分族 → 管道五组（全枚举）。"""

    def test_every_family_maps_to_coarse_group(self):
        for family in ALGO_FAMILIES:
            assert coarse_group(family) in {"vwap", "twap", "pov", "close", "other"}, family

    def test_expected_mappings(self):
        assert coarse_group("vwap") == "vwap"
        assert coarse_group("twap") == "twap"
        assert coarse_group("pov") == "pov"
        assert coarse_group("auction_close") == "close"
        assert coarse_group("close") == "close"
        assert coarse_group("auction_open") == "other"
        assert coarse_group("liquidity") == "other"
        assert coarse_group("unmapped") == "other"

    def test_unknown_family_falls_back_to_other(self):
        assert coarse_group("future_family") == "other"


class TestIntentFamilies:
    """用例 5：意图 → 族。"""

    def test_five_benchmarks(self):
        assert intent_families("VWAP") == ("vwap",)
        assert intent_families("CLOSE") == ("auction_close",)
        assert intent_families("MIX") == ("auction_close", "vwap")
        assert intent_families("SPECIAL") == ()
        assert intent_families("UNMAPPED") == ()

    def test_table_matches_function(self):
        for benchmark, families in INTENT_TO_FAMILIES.items():
            assert intent_families(benchmark) == families


class TestPipelineGapConsistency:
    """用例 6：与管道 algo 的一致性（差异 ⊆ 已知缺口）。"""

    def test_known_gaps_differ_from_pipeline(self):
        # 已知缺口组合的 coarse 必须 ≠ 管道 algo（否则清单过期）
        for key, (mine, pipeline_algo, _note) in KNOWN_PIPELINE_GAPS.items():
            assert coarse_group(classify_algo(*key)) == mine, key
            assert mine != pipeline_algo, key

    def test_non_gap_combos_match_pipeline(self):
        # 管道 algo 标注（来自真实分布的非缺口组合）
        pipeline_algo = {
            ("EQ-MS", "CLOSE"): "close",
            ("EQ-GS", "AUCTION"): "close",
            ("EQ-BARCLAY", "VWAP-EU"): "vwap",
            ("EQ-HSBC", "POV."): "pov",
            ("EQ-JPM", "TWAP"): "twap",
            ("EQ-NOMURA", "Custom"): "close",
            ("EQ-UBS", "CUSTOM2"): "close",
            ("CROSSING", None): "other",
            ("EQ-BMO", "OnOpen"): "other",  # auction_open→other 与管道一致
        }
        for (broker, strategy), expected in pipeline_algo.items():
            key = (broker, normalize_strategy_type(strategy))
            assert key not in KNOWN_PIPELINE_GAPS
            assert coarse_group(classify_algo(broker, strategy)) == expected, key


class TestCoverageOf:
    """用例 7：覆盖率统计。"""

    def test_stats_and_threshold(self):
        rows = [
            ("EQ-MS", "CLOSE", 1000),
            ("EQ-GS", "VWAP", 500),
            ("EQ-NEW", "MYSTERY", 10),
        ]
        stats = coverage_of(rows)
        assert stats["total"] == 1510
        assert stats["covered"] == 1500
        assert stats["unmapped"] == 10
        assert stats["coverage_pct"] == round(1500 / 1510 * 100, 4)
        assert stats["unmapped_list"] == [("EQ-NEW", "MYSTERY", 10)]

    def test_gap_counts_do_not_reduce_coverage(self):
        rows = [("EQ-BOCI", "POV", 369), ("EQ-BNP", "MOC", 100)]
        stats = coverage_of(rows)
        # 已知缺口组合仍计入 covered（细分族命中），另计 gap_counts
        assert stats["covered"] == 469
        assert stats["gap_counts"][("EQ-BOCI", "POV")] == 369

    def test_empty_rows(self):
        stats = coverage_of([])
        assert stats["total"] == 0
        assert stats["coverage_pct"] == 0.0
        assert stats["unmapped_list"] == []


def test_version_present():
    assert ALGO_TAXONOMY_VERSION == "algo-taxonomy-v1"
    assert FAMILY_TO_COARSE.keys() == set(ALGO_FAMILIES)
    assert len(STRATEGY_TYPE_MAP) >= 90
