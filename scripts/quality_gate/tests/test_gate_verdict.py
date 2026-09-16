"""门禁判定语义测试 — OE guard 基线演进 + 首次扫描放行（ADR-0021）。

覆盖两类易回归点：
1. ``gate_verdict`` 的存量 / 新增划分（含首次扫描语义）；
2. ``GateStore.has_baseline`` 能把「首次扫描」与「存量已全部清偿」区分开。
"""
from __future__ import annotations

from scripts.quality_gate.models import Finding, RuleSet, Severity
from scripts.quality_gate.scoring import gate_verdict
from scripts.quality_gate.store import GateStore


def _finding(rule_id: str, ruleset: RuleSet, fingerprint: str) -> Finding:
    """构造最小 Finding（仅门禁判定所需字段）。"""
    return Finding(
        rule_id=rule_id,
        ruleset=ruleset,
        severity=Severity.LOW,
        file="a/b.py",
        line=1,
        symbol="sym",
        message="msg",
        fix_hint="hint",
        fingerprint=fingerprint,
    )


class TestGateVerdict:
    """OE guard 语义。"""

    def test_known_oe_is_existing_unknown_is_new(self):
        known = _finding("OE-05", RuleSet.OE, "fp-known")
        fresh = _finding("OE-07", RuleSet.OE, "fp-fresh")

        verdict = gate_verdict([known, fresh], {"fp-known"})

        assert verdict["oe_new"] == [fresh]
        assert verdict["oe_existing"] == [known]

    def test_ap_violations_always_reported(self):
        ap = _finding("AP-01", RuleSet.AP, "fp-ap")

        verdict = gate_verdict([ap], set())

        assert verdict["ap_violations"] == [ap]
        assert verdict["oe_new"] == []

    def test_first_scan_treats_all_oe_as_baseline(self):
        """基线库为空（首次扫描）：全部 OE 记存量，不判新增。"""
        findings = [
            _finding("OE-05", RuleSet.OE, "fp-1"),
            _finding("OE-07", RuleSet.OE, "fp-2"),
        ]

        verdict = gate_verdict(findings, set(), baseline_established=False)

        assert verdict["oe_new"] == []
        assert verdict["oe_existing"] == findings

    def test_first_scan_does_not_exempt_ap(self):
        """首次扫描只豁免 OE 基线判定，不豁免 AP 契约违规。"""
        ap = _finding("AP-01", RuleSet.AP, "fp-ap")
        oe = _finding("OE-05", RuleSet.OE, "fp-oe")

        verdict = gate_verdict([ap, oe], set(), baseline_established=False)

        assert verdict["ap_violations"] == [ap]
        assert verdict["oe_new"] == []
        assert verdict["oe_existing"] == [oe]


class TestStoreHasBaseline:
    """``has_baseline`` 用于区分「首次扫描」与「存量已清偿」。"""

    def test_empty_db_has_no_baseline(self, tmp_path):
        store = GateStore(tmp_path / "qg.db")
        try:
            assert store.has_baseline() is False

            store.upsert_baseline([_finding("OE-05", RuleSet.OE, "fp-1")])

            assert store.has_baseline() is True
        finally:
            store.close()

    def test_all_open_items_fixed_still_counts_as_established(self, tmp_path):
        """存量全部清偿（open 集合为空）不得退化为「首次扫描」。"""
        store = GateStore(tmp_path / "qg.db")
        try:
            store.upsert_baseline([_finding("OE-05", RuleSet.OE, "fp-1")])
            store.mark_fixed_missing(set())

            assert store.load_open_fingerprints("oe") == set()
            assert store.has_baseline() is True
        finally:
            store.close()
