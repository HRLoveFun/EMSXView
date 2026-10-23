"""057 DL-13（068）：预期成本与 timing risk 模型测试。

覆盖子规格 §2.3 检验方法：
1. 纯函数（timing_risk σ√T / required_duration / close_capacity / 域检查）；
2. 拟合集成（tmp 双库夹具）：市场组分组、样本不足组不产模型、save/load 往返；
3. 契约互锁（COST_MODEL_VERSION 两侧一致 + OrderDifficulty 字段完整）；
4. 时间切分样本外校准（真实数据，见 PR 描述的成本校准输出）。

夹具全部虚构数据（市场 ZZ、SEC_A/B 虚构 ticker、人造参与率/波动/冲击序列）。
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from CostView.src.evaluation.expected_cost import (  # noqa: E402
    COST_MODEL_VERSION,
    close_capacity_pct,
    expected_cost_bps,
    fit_expected_cost_models,
    load_expected_cost_model,
    model_path,
    required_duration_min,
    save_models,
    timing_risk_bps,
)
from CostView.src.evaluation.cost_model import ImpactModel  # noqa: E402
from data_access.storage.connection import ConnectionManager  # noqa: E402
from platform_data.contracts import COST_MODEL_VERSION as CONTRACT_VERSION, OrderDifficulty  # noqa: E402


class TestPureFunctions:
    """① 纯函数。"""

    def test_timing_risk_sqrt_t(self):
        # 年化 25.5%（√252≈15.87）日 σ≈1.607%；T=65min/US 会话 390min → ×√(1/6)≈0.408
        risk = timing_risk_bps(25.5, 65, 390)
        expected = 25.5 / math.sqrt(252) * math.sqrt(65 / 390) * 100
        assert risk == round(expected, 2)

    def test_timing_risk_invalid(self):
        assert timing_risk_bps(None, 65, 390) is None
        assert timing_risk_bps(0, 65, 390) is None
        assert timing_risk_bps(25.0, 0, 390) is None

    def test_required_duration(self):
        # 100,000 股 ÷ (10% × 1,000,000 ADV) = 1 分钟
        assert required_duration_min(100_000, 0.10, 1_000_000) == 1.0
        assert required_duration_min(100_000, 0.0, 1_000_000) is None
        assert required_duration_min(100_000, 0.10, None) is None

    def test_close_capacity(self):
        assert close_capacity_pct(50_000, 500_000) == 10.0
        assert close_capacity_pct(50_000, None) is None
        assert close_capacity_pct(0, 500_000) is None

    def test_expected_cost_domain(self):
        model = ImpactModel(
            intercept=1.0,
            slope_participation=0.5,
            slope_volatility=0.3,
            n_observations=100,
            r_squared=0.5,
            participation_domain=(0.01, 0.5),
            volatility_domain=(10.0, 60.0),
        )
        assert expected_cost_bps(model, 0.1, 25.0) is not None
        assert expected_cost_bps(model, 0.9, 25.0) is None  # 域外
        assert expected_cost_bps(None, 0.1, 25.0) is None  # 无模型


@pytest.fixture()
def cost_dbs(tmp_path: Path):
    """fill_bdib（tca_route_summary）+ raw_bdib（bdib_daily_summary）夹具。

    ZZ 市场 40 条样本（参与率/波动/冲击人造相关序列）；QQ 市场 10 条（样本不足）。
    """
    fb = tmp_path / "fill_bdib.db"
    conn = sqlite3.connect(str(fb))
    conn.execute(
        "CREATE TABLE tca_route_summary ("
        "OrderId TEXT, RouteId TEXT, order_as_of_date TEXT, Exchange TEXT, equ_ticker TEXT, "
        "RouteShares REAL, temp_impact_30min_bps REAL, arrival_cost_bps REAL, order_duration_sec REAL)"
    )
    rows = []
    adv20 = 1_000_000  # 夹具 ADV20（bdib_daily_summary 同值）
    for i in range(40):
        intent_p = 0.02 + i * 0.001  # 意图参与率（决策时点外生）
        vol = 20.0 + (i % 10)
        impact = 5.0 * (intent_p / 0.02) ** 0.5 * (vol / 20.0) ** 0.3  # 人造幂律
        shares = intent_p * adv20
        trade_date = f"2026{8 + (i // 28):02d}{i % 28 + 1:02d}"  # 40 个不同日期（join 键唯一）
        rows.append(("O1", "R1", trade_date, "ZZ", "SEC_A US Equity", shares, impact, impact, 3600))
    for i in range(10):  # QQ 样本不足（<30）
        rows.append(("O2", "R2", "20260801", "QQ", "SEC_B US Equity", 50_000, 10.0, 10.0, 1800))
    conn.executemany("INSERT INTO tca_route_summary VALUES (?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()

    rb = tmp_path / "raw_bdib.db"
    conn = sqlite3.connect(str(rb))
    conn.execute(
        "CREATE TABLE bdib_daily_summary ("
        "equ_ticker TEXT, trade_date TEXT, total_volume REAL, daily_vwap REAL, "
        "daily_volatility REAL, adv_5d REAL, adv_20d REAL, computed_at TEXT, "
        "daily_close REAL, intraday_volatility REAL)"
    )
    conn.executemany(
        "INSERT INTO bdib_daily_summary VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            ("SEC_A US Equity", f"2026{8 + (i // 28):02d}{i % 28 + 1:02d}", 1e6, 100.0, 20.0 + (i % 10), 9e5, 1e6, "x", 100.0, 0.02)
            for i in range(40)
        ],
    )
    conn.commit()
    conn.close()

    from unittest.mock import patch

    mgr = ConnectionManager(
        path_overrides={"fill_bdib": fb, "raw_bdib": rb}
    )
    return mgr


class TestFitIntegration:
    """② 拟合集成。"""

    def test_fit_by_market_and_min_samples(self, cost_dbs):
        models = fit_expected_cost_models(
            cost_dbs, start_date="20260101", end_date="20261231", min_observations=30
        )

        assert set(models) == {"ZZ"}  # QQ 样本不足不产模型
        model = models["ZZ"]
        assert model.n_observations == 40
        assert 0 < model.r_squared <= 1
        assert model.participation_domain[0] < model.participation_domain[1]
        # 参与率 = RouteShares/ADV20（意图参与率，外生口径）
        assert abs(model.participation_domain[0] - 0.02) < 1e-9

    def test_save_and_load_roundtrip(self, cost_dbs, tmp_path, monkeypatch):
        import CostView.src.evaluation.expected_cost as ec

        # 模型目录指向 tmp（避免污染包内产物）
        monkeypatch.setattr(ec, "MODELS_DIR", tmp_path / "models")
        models = fit_expected_cost_models(cost_dbs, start_date="20260101", end_date="20261231")
        written = save_models(models, window="20260101~20261231")

        assert len(written) == 1
        assert written[0].name == f"impact_ZZ_{COST_MODEL_VERSION}.json"
        loaded = load_expected_cost_model("ZZ")
        assert loaded is not None
        assert loaded.intercept == models["ZZ"].intercept
        assert loaded.n_observations == 40

    def test_load_missing_returns_none(self, tmp_path, monkeypatch):
        import CostView.src.evaluation.expected_cost as ec

        monkeypatch.setattr(ec, "MODELS_DIR", tmp_path / "empty")
        assert load_expected_cost_model("ZZ") is None


class TestContractLock:
    """③ 契约互锁。"""

    def test_version_consistent(self):
        assert CONTRACT_VERSION == COST_MODEL_VERSION

    def test_order_difficulty_fields(self):
        from dataclasses import fields

        names = {f.name for f in fields(OrderDifficulty)}
        assert names == {
            "expected_cost_bps",
            "timing_risk_bps",
            "required_duration_min",
            "close_capacity_pct",
            "model_version",
            "in_domain",
            "notes",
        }
        difficulty = OrderDifficulty(
            expected_cost_bps=12.5,
            timing_risk_bps=8.0,
            required_duration_min=65.0,
            close_capacity_pct=15.0,
            model_version=COST_MODEL_VERSION,
            in_domain=True,
        )
        assert difficulty.in_domain is True
