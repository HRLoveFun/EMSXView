"""057 DL-16（070）：策略注册表测试。

覆盖：归一化、族归类（白名单 110 名核心）、参数校验、默认值回填、
校验服务三态、版本常量。夹具为虚拟 broker/策略，无真实业务数据。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts import (  # noqa: E402
    REGISTRY_VERSION,
    STRATEGY_REGISTRY,
    default_params,
    normalize_algo_name,
    resolve_family,
    validate_strategy_params,
)
from services.strategy_registry import validate_route_submission  # noqa: E402


class TestNormalizeAndFamily:
    """① 归一化与族归类。"""

    def test_normalize(self):
        assert normalize_algo_name("VWAP.") == "VWAP"
        assert normalize_algo_name(" twap-eu ") == "TWAP-EU"
        assert normalize_algo_name(None) == ""

    def test_resolve_family_core_names(self):
        # 白名单 110 名中的核心命名变体（跨 broker 不一致）
        assert resolve_family("VWAP") == "vwap"
        assert resolve_family("VWAP-EU") == "vwap"
        assert resolve_family("TClose") == "auction_close"
        assert resolve_family("SmartMOC") == "auction_close"
        assert resolve_family("IntoClose") == "auction_close"
        assert resolve_family("OnOpen") == "auction_open"
        assert resolve_family("With-Vol") == "pov"
        assert resolve_family("PARTCIPTE") == "pov"
        assert resolve_family("IS") == "is"
        assert resolve_family("SMART DMA") == "dma"
        assert resolve_family("CUSTOM2") == "close"

    def test_resolve_family_unmapped_explicit(self):
        # broker 专有高级算法 → unmapped（显式，不静默归 other）
        assert resolve_family("Hydra") == "unmapped"
        assert resolve_family("Escalate") == "unmapped"

    def test_registry_seed_families_match_resolve(self):
        # 注册表条目的 family 与 resolve_family 一致（双源不漂移）
        for name, spec in STRATEGY_REGISTRY.items():
            assert resolve_family(name) == spec.family, name


class TestValidateParams:
    """② 参数校验。"""

    def test_pov_missing_required(self):
        errors = validate_strategy_params("POV", {})
        assert len(errors) == 1
        assert "participation_rate" in errors[0]

    def test_pov_type_mismatch(self):
        errors = validate_strategy_params("POV", {"participation_rate": "high"})
        assert any("应为数值" in e for e in errors)

    def test_vwap_optional_ok(self):
        assert validate_strategy_params("VWAP", {"participation_rate": 0.18}) == []
        assert validate_strategy_params("VWAP", {}) == []

    def test_unknown_strategy_not_blocked(self):
        # broker 专有算法未入注册表 → 不阻断（族级归类即可）
        assert validate_strategy_params("Hydra", {"foo": 1}) == []

    def test_normalized_name_lookup(self):
        assert validate_strategy_params("pov.", {"participation_rate": 0.1}) == []


class TestDefaults:
    """③ 默认值回填。"""

    def test_default_params(self):
        assert default_params("IS") == {"urgency": "MEDIUM"}
        assert default_params("VWAP") == {}  # 通用参数无默认值
        assert default_params("Hydra") == {}  # 未入注册表


class TestValidationService:
    """④ 校验服务（057 DL-17c/073：未配置→WARN 部署初期例外；已配置未命中→BLOCK）。"""

    def test_no_whitelist_warns_not_blocks(self, monkeypatch):
        """白名单未配置 = 部署初期状态 → WARN（与 071 configured 语义一致）。"""
        monkeypatch.delenv("EMSXVIEW_ALGO_WHITELIST", raising=False)
        result = validate_route_submission("EQ-MS", "VWAP", {"participation_rate": 0.18})

        assert result.errors == []
        assert any("not configured" in w for w in result.warnings)

    def test_registry_error_blocks(self, monkeypatch):
        monkeypatch.delenv("EMSXVIEW_ALGO_WHITELIST", raising=False)
        result = validate_route_submission("EQ-MS", "POV", {})

        assert result.errors  # 必填缺失 → 阻断
        assert result.registry_version == REGISTRY_VERSION

    def test_unmapped_family_warns(self, monkeypatch):
        monkeypatch.delenv("EMSXVIEW_ALGO_WHITELIST", raising=False)
        result = validate_route_submission("EQ-GS", "Hydra", {})

        assert any("unmapped" in w for w in result.warnings)

    def test_configured_whitelist_miss_blocks(self, monkeypatch, tmp_path):
        """白名单已配置但查不到该 (broker, algo) → BLOCK（交易员意见第 11 项）。"""
        fixture = Path(__file__).resolve().parent / "fixtures" / "algo_whitelist_sample.xlsx"
        monkeypatch.setenv("EMSXVIEW_ALGO_WHITELIST", str(fixture))

        # EQ-FAKE1 的名单只有 VWAP/TWAP/POV/CLOSE——IS 未命中 → BLOCK
        result = validate_route_submission("EQ-FAKE1", "IS", {})

        assert result.errors
        assert any("algo whitelist" in error for error in result.errors)

        # 命中 → 无白名单相关 error
        allowed = validate_route_submission("EQ-FAKE1", "VWAP", {})
        assert not any("algo whitelist" in error for error in allowed.errors)


def test_version_constant():
    assert REGISTRY_VERSION == "strategy-registry-v1"
