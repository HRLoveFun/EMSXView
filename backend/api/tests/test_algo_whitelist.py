"""057 DL-16（070）：外部算法白名单测试（用户 2026-10-23 追加）。

夹具 `fixtures/algo_whitelist_sample.xlsx` 为样板格式虚拟数据
（EQ-FAKE1/2/3，含大小写与尾点变体、NONE 忽略）。无真实业务数据。
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
    WHITELIST_PATH_ENV,
    AlgoWhitelist,
    compliance_check,
    is_algo_whitelisted,
    load_algo_whitelist,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "algo_whitelist_sample.xlsx"


@pytest.fixture()
def whitelist() -> AlgoWhitelist:
    loaded = load_algo_whitelist(str(FIXTURE))
    assert loaded is not None
    return loaded


class TestLoad:
    """① 样板格式加载。"""

    def test_load_fixture(self, whitelist):
        # 3 个虚拟 broker（含全 NONE 的 EQ-FAKE3）
        assert whitelist.row_count == 3
        assert set(whitelist.brokers) == {"EQ-FAKE1", "EQ-FAKE2", "EQ-FAKE3"}
        assert whitelist.brokers["EQ-FAKE3"] == frozenset()
        assert whitelist.source_path == str(FIXTURE)
        assert whitelist.loaded_at

    def test_normalization_on_load(self, whitelist):
        # POV.（尾点）→ POV；大小写归一
        assert "POV" in whitelist.brokers["EQ-FAKE1"]
        assert "TWAP" in whitelist.brokers["EQ-FAKE1"]

    def test_missing_file_returns_none(self, tmp_path):
        assert load_algo_whitelist(str(tmp_path / "nope.xlsx")) is None

    def test_unconfigured_returns_none(self, monkeypatch):
        monkeypatch.delenv(WHITELIST_PATH_ENV, raising=False)
        assert load_algo_whitelist() is None


class TestVerdict:
    """② 三态判定。"""

    def test_in_whitelist(self, whitelist):
        assert is_algo_whitelisted(whitelist, "EQ-FAKE1", "VWAP") is True
        assert is_algo_whitelisted(whitelist, "eq-fake1", "pov.") is True  # 大小写/尾点

    def test_not_in_whitelist(self, whitelist):
        assert is_algo_whitelisted(whitelist, "EQ-FAKE1", "IS") is False  # 该 broker 无 IS
        assert is_algo_whitelisted(whitelist, "EQ-FAKE3", "VWAP") is False  # 全 NONE broker
        assert is_algo_whitelisted(whitelist, "EQ-UNKNOWN", "VWAP") is False  # broker 不在名单

    def test_unknown_whitelist_returns_none(self):
        assert is_algo_whitelisted(None, "EQ-FAKE1", "VWAP") is None


class TestComplianceCheck:
    """③ 合规检查三态。"""

    def test_allowed_in_list(self, whitelist):
        result = compliance_check(whitelist, "EQ-FAKE2", "MOC")
        assert result.allowed is True
        assert result.reason == "in algo whitelist"

    def test_blocked_not_in_list(self, whitelist):
        result = compliance_check(whitelist, "EQ-FAKE1", "IS")
        assert result.allowed is False
        assert "not in algo whitelist" in result.reason

    def test_unknown_passes_with_reason(self):
        result = compliance_check(None, "EQ-FAKE1", "VWAP")
        assert result.allowed is True
        assert "unavailable" in result.reason
