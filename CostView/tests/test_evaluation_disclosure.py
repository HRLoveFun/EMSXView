"""节点三披露（2026-11-27）：HTML 归档包含 D1 / 排名 v2 / 券商分项得分摘要。"""

from __future__ import annotations

from CostView.src.monitoring.tca_report_html import _render_evaluation_section


def _evaluation_payload() -> dict:
    return {
        "primary_benchmark": "arrival",
        "sections": {
            "dimensions": [
                {
                    "dimension": "broker",
                    "group_count": 1,
                    "rows": [{"vs_others": {"confidence": "high"}}],
                    "highlights": {},
                }
            ],
            "pairing": {
                "coverage": {
                    "total_orders": 100,
                    "candidate_orders": 5,
                    "candidate_pct": 5.0,
                    "groups": 5,
                    "grouped_routes": 12,
                    "relative_cost_routes": 10,
                    "brokers": 2,
                },
                "rule": {"min_brokers": 2, "max_spread_minutes": 5, "min_pairs_for_test": 10},
                "broker_pair_tests": [
                    {
                        "broker_a": "EQ-A",
                        "broker_b": "EQ-B",
                        "pairs": 12,
                        "median_diff_bps": -1.2,
                        "wilcoxon": {"p_value": 0.03},
                    }
                ],
            },
            "ranking": {
                "available": True,
                "method": "cluster-robust + shrinkage",
                "metric": "arrival_cost_bps",
                "top_k": 3,
                "units": [
                    {
                        "broker": "EQ-A",
                        "n": 50,
                        "posterior_mean": -5.0,
                        "posterior_ci_low": -7.0,
                        "posterior_ci_high": -3.0,
                        "p_top_k": 0.8,
                        "low_sample": False,
                    }
                ],
                "indistinguishable": ["EQ-A", "EQ-B"],
            },
            "broker_scores": {
                "available": True,
                "window_start": "20261120",
                "window_end": "20261120",
                "coverage": {"routes": 50, "brokers": 1, "misaligned_samples": 0},
                "snapshots": [
                    {
                        "broker": "EQ-A",
                        "components": [
                            {"name": "cost", "value": -5.0, "unit": "bps", "sample_size": 50, "available": True},
                            {"name": "tail_risk", "value": 1.0, "unit": "z", "sample_size": 50, "available": True},
                            {"name": "completion", "value": 0.99, "unit": "ratio", "sample_size": 50, "available": True},
                            {"name": "opportunity_cost", "value": 0.0, "unit": "currency", "sample_size": 50, "available": True},
                            {"name": "leakage", "value": None, "unit": "bps", "sample_size": 0, "available": False},
                            {"name": "operational", "value": 1.0, "unit": "ratio", "sample_size": 50, "available": True},
                        ],
                    }
                ],
            },
        },
    }


def test_evaluation_section_includes_node3_disclosures() -> None:
    html = _render_evaluation_section(_evaluation_payload())

    assert "D1 订单内配对" in html
    assert "5/100" in html
    assert "EQ-A vs EQ-B" in html

    assert "券商排名 v2" in html
    assert "后验均值" in html
    assert "95% 区间" in html
    assert "P(top-k)" in html
    assert "不可区分集合 2 家" in html

    assert "券商分项得分" in html
    assert "信息泄露分项当前不可得" in html
