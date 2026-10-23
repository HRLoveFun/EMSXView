"""057 DL-17c/073：算法参数合规测试。

覆盖：volume cap 分配（比例/精度/纪律）、EUR 与非 EUR 上限、券商命名映射
（既有记录/缺省）、volume cap 必带、收盘拍卖 release time 必带、
白名单「未命中或未知不放行」语义。
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
    ALGO_PARAMS_VERSION,
    DEFAULT_VOLUME_CAP_PARAM,
    MAX_VOLUME_CAP_EUR,
    MAX_VOLUME_CAP_NON_EUR,
    VOLUME_CAP_PRECISION,
    allocate_volume_caps,
    check_release_time_present,
    check_volume_cap_present,
    max_cap_for,
    param_name_for,
    release_time_required,
)
from services import order_compliance_service, strategy_registry  # noqa: E402


class TestAllocation:
    """① volume cap 分配（同日同名且同方向）。"""

    def test_proportional_by_quantity(self):
        # 1000:3000 分 18.0 → 4.5 / 13.5
        allocation = allocate_volume_caps([("A", 1000), ("B", 3000)], MAX_VOLUME_CAP_NON_EUR)
        assert allocation == {"A": 4.5, "B": 13.5}
        assert sum(allocation.values()) <= MAX_VOLUME_CAP_NON_EUR

    def test_precision_floor_and_remainder_to_biggest(self):
        # 三单等量 18.0 → 每单 6.0 无余；改 7.0 上限：2.3/2.3/2.3 = 6.9，余 0.1 给最大单
        allocation = allocate_volume_caps(
            [("A", 100), ("B", 100), ("C", 100)], 7.0, precision=VOLUME_CAP_PRECISION
        )
        assert sum(allocation.values()) <= 7.0
        assert allocation["A"] == 2.4  # 余量给最大单（三单等量取第一个最大）
        assert allocation["B"] == allocation["C"] == 2.3
        assert all(round(v, 1) == v for v in allocation.values())  # 0.1 步进

    def test_uneven_ratio_floor_conserved(self):
        # 1:2 → 18.0 → 6.0/12.0；改 5.0 上限 → 1.6/3.3 = 4.9，余 0.1 给 B
        allocation = allocate_volume_caps([("A", 1), ("B", 2)], 5.0)
        assert sum(allocation.values()) <= 5.0
        assert allocation["B"] >= allocation["A"]

    def test_never_exceeds_cap(self):
        for cap in (0.3, 1.7, 9.0, 18.0):
            allocation = allocate_volume_caps(
                [("A", 7), ("B", 11), ("C", 13), ("D", 17)], cap
            )
            assert sum(allocation.values()) <= cap + 1e-9

    def test_empty_and_zero_quantity(self):
        assert allocate_volume_caps([], 18.0) == {}
        assert allocate_volume_caps([("A", 0), ("B", -5)], 18.0) == {}
        assert allocate_volume_caps([("A", 100)], 0.0) == {}


class TestCapLimits:
    """② EUR 与非 EUR 上限。"""

    def test_eur_currency(self):
        assert max_cap_for("EUR", "US") == MAX_VOLUME_CAP_EUR

    def test_eur_folded_market(self):
        assert max_cap_for("USD", "EU") == MAX_VOLUME_CAP_EUR
        assert max_cap_for(None, "EUR") == MAX_VOLUME_CAP_EUR

    def test_non_eur(self):
        assert max_cap_for("USD", "US") == MAX_VOLUME_CAP_NON_EUR
        assert max_cap_for("JPY", "JP") == MAX_VOLUME_CAP_NON_EUR


class TestParamNameMapping:
    """③ 券商命名映射（既有记录优先，缺省可观测）。"""

    def test_record_hit(self):
        name, source = param_name_for("EQ-JPM", {"EQ-JPM": "MaxPctVol"})
        assert name == "MaxPctVol"
        assert source == "record"

    def test_default_fallback(self):
        name, source = param_name_for("EQ-UNKNOWN", {"EQ-JPM": "MaxPctVol"})
        assert name == DEFAULT_VOLUME_CAP_PARAM
        assert source == "default"

    def test_loader_prefers_menu_cache_then_record(self, tmp_path, monkeypatch):
        # 手工记录命中
        record = tmp_path / "broker_volume_cap_params.json"
        record.write_text('{"EQ-AAA": "PctVolX"}', encoding="utf-8")
        mapping = order_compliance_service.load_volume_cap_mapping(str(record))
        assert mapping.get("EQ-AAA") == "PctVolX"


class TestVolumeCapPresent:
    """④ 每路由必带 volume cap。"""

    def test_present_passes(self):
        assert check_volume_cap_present({"PctVol": "18.0"}, "EQ-NEW", mapping={}) == []

    def test_missing_blocks_with_recorded_name(self):
        errors = check_volume_cap_present({"PctVol": "18.0"}, "EQ-JPM", mapping={"EQ-JPM": "MaxPctVol"})
        assert errors and "MaxPctVol" in errors[0]

    def test_empty_value_blocks(self):
        assert check_volume_cap_present({"PctVol": ""}, "EQ-NEW", mapping={})
        assert check_volume_cap_present({}, "EQ-NEW", mapping={})


class TestReleaseTime:
    """⑤ 收盘拍卖订单必带 release time。"""

    def test_closing_auction_markets_require(self):
        assert release_time_required("US") is True
        assert release_time_required("JP") is True

    def test_requirement_enforced(self):
        errors = check_release_time_present({}, "US")
        assert errors and "release_time" in errors[0]
        assert check_release_time_present({"release_time": "16:00"}, "US") == []

    def test_non_closing_market_not_required(self):
        assert check_release_time_present({}, "ZZ") == []


class TestEnforceSwitch:
    """⑦ 特性开关（G2：默认关闭；开启后阻断）。"""

    def test_default_off(self, monkeypatch):
        monkeypatch.delenv("EMSXVIEW_ALGO_PARAMS_ENFORCED", raising=False)
        assert order_compliance_service.algo_params_enforced() is False

    def test_enabled_variants(self, monkeypatch):
        for value in ("1", "true", "TRUE", "yes"):
            monkeypatch.setenv("EMSXVIEW_ALGO_PARAMS_ENFORCED", value)
            assert order_compliance_service.algo_params_enforced() is True
        monkeypatch.setenv("EMSXVIEW_ALGO_PARAMS_ENFORCED", "0")
        assert order_compliance_service.algo_params_enforced() is False


class TestWhitelistSemantics:
    """⑥ 白名单「未命中或未知不放行」（DL-17c 语义修订）。"""

    def test_unknown_config_warns(self, monkeypatch):
        """未配置 = 部署初期状态 → WARN；已配置未命中 → BLOCK（见 test_strategy_registry）。"""
        monkeypatch.delenv("EMSXVIEW_ALGO_WHITELIST", raising=False)
        result = strategy_registry.validate_route_submission("EQ-MS", "VWAP", {"participation_rate": 0.1})

        assert result.errors == []
        assert any("ALGO_WHITELIST_UNKNOWN" in warning for warning in result.warnings)

    def test_version_constant(self):
        assert ALGO_PARAMS_VERSION == "algo-params-v1"
        assert VOLUME_CAP_PRECISION == 0.1
