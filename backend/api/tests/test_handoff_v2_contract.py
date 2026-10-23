"""057 DL-14：handoff v2 契约测试。

锁死行为：
1. HANDOFF_SCHEMA_VERSION 常量与载荷扩展字段（v1 兼容）；
2. PreTradeBoardItem 字段完整（四路产物 + 未达标标注 + data_gaps）；
3. v1 契约（ExecutionCandidateHandoff）字段不变（向后兼容）。
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    HANDOFF_MAX_STRATEGY_PARAMS_BYTES,
    HANDOFF_SCHEMA_VERSION,
    ExecutionCandidateHandoff,
    PreTradeBoardItem,
)


class TestHandoffV2Contract:
    """①② v2 载荷版本与字段。"""

    def test_schema_version_constant(self):
        assert HANDOFF_SCHEMA_VERSION == "market-to-execution-v2"

    def test_pretrade_board_item_fields(self):
        names = {f.name for f in fields(PreTradeBoardItem)}
        assert names == {
            "equ_ticker", "order_key", "benchmark", "close_pct", "qty",
            "log_volume_z", "vol_percentile", "adv5_adv60_ratio",
            "market_code", "liq_regime", "vol_regime",
            "expected_cost_bps", "timing_risk_bps", "in_domain",
            "model_version", "model_calibrated", "data_gaps",
        }

    def test_pretrade_board_item_defaults(self):
        item = PreTradeBoardItem(
            equ_ticker="SEC_A US Equity",
            order_key="^7000001^0",
            benchmark="VWAP",
            close_pct=None,
            qty=50_000,
        )
        # 缺省降级可见：未达标标注 False、域外 False、无缺口
        assert item.model_calibrated is False
        assert item.in_domain is False
        assert item.data_gaps == ()
        assert item.log_volume_z is None

    def test_v1_contract_unchanged(self):
        """v1 载荷字段不变（扩展而非替换——旧消费方不破）。"""
        names = {f.name for f in fields(ExecutionCandidateHandoff)}
        assert names == {
            "metadata", "trade_date", "pool_id", "pool_label",
            "candidate_payload", "execution_hint",
        }
        assert HANDOFF_MAX_STRATEGY_PARAMS_BYTES == 64 * 1024
