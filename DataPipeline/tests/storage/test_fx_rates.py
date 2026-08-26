"""fx_rate 持久化（fx-rate-persistence）单元测试。

覆盖:
    Part 1: SqliteFxRatesRepository CRUD —— 精确命中 / 批量 / 有界回退 /
            幂等 REPLACE / 键规范化 / 脏值过滤
    Part 2: fx_fetcher 拉取链 —— 查表优先（零 Bloomberg 调用）/ 成功落表 /
            降级链（表有界回退 → 内存缓存 → 1.0）/ 降级值不落表 /
            有界回退优先于无日期维度的内存缓存（防未来汇率泄漏）
"""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pandas as pd
import pytest

import DataPipeline.acquisition.fx_fetcher as fx_module
from DataPipeline.acquisition.fx_fetcher import fetch_fx_rate_for_ccy
from DataPipeline.storage.repositories.fx_rates import SqliteFxRatesRepository
from DataPipeline.storage.schema.inline_ddl import init_fx_rates_schema


# ── 测试辅助: 可注入 :memory: DB 的 Repository 子类 ───────────────────────

#: 仓储存储键为规范化大写（_norm_ccy），直接 SQL 断言需用该形式
_JPY_NORM = "USDJPY CURNCY"


class _ConnWrapper:
    """让 close() 变 no-op, 避免一次调用就关闭共享 :memory: conn."""

    def __init__(self, conn: sqlite3.Connection):
        self._c = conn

    def execute(self, sql, params=()):
        return self._c.execute(sql, params)

    def executemany(self, sql, params):
        return self._c.executemany(sql, params)

    def commit(self):
        self._c.commit()

    def close(self):
        pass  # 测试中不关闭共享连接


class _InMemoryFxRepo(SqliteFxRatesRepository):
    """绕过 ConnectionManager, 直接使用 :memory: sqlite connection."""

    def __init__(self, conn: sqlite3.Connection):
        # 不调 super().__init__ 以避免创建 ConnectionManager
        self._conn = conn

    def _get_read_conn(self):
        return _ConnWrapper(self._conn)

    def _get_write_conn(self):
        return _ConnWrapper(self._conn)


@pytest.fixture
def fx_db() -> sqlite3.Connection:
    """:memory: fill_bdib 连接，含 fx_rates 表。"""
    conn = sqlite3.connect(":memory:")
    init_fx_rates_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def _clear_recent_rates():
    """隔离 fx_fetcher 模块级 _RECENT_RATES 内存缓存。"""
    fx_module._RECENT_RATES.clear()
    yield
    fx_module._RECENT_RATES.clear()


# ═══════════════════════════════════════════════════════════════════════
# Part 1: SqliteFxRatesRepository CRUD
# ═══════════════════════════════════════════════════════════════════════


def test_upsert_and_get_rate_exact_hit(fx_db):
    """upsert 后精确查询命中；未命中返回 None。"""
    repo = _InMemoryFxRepo(fx_db)
    assert repo.get_rate("USDJPY Curncy", "20260101") is None
    assert repo.upsert_rate("USDJPY Curncy", "20260101", 0.00697, 143.5) == 1
    assert repo.get_rate("USDJPY Curncy", "20260101") == pytest.approx(0.00697)
    assert repo.get_rate("USDJPY Curncy", "20260102") is None


def test_key_normalization_roundtrip(fx_db):
    """小写/带空白的键写入后可用规范键查到（键统一 upper().strip()）。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("  usdjpy curncy ", "20260101", 0.00697)
    assert repo.get_rate("USDJPY CURNCY", "20260101") == pytest.approx(0.00697)
    assert repo.get_rate("usdjpy curncy", "20260101") == pytest.approx(0.00697)


def test_get_rates_for_date_batch_preserves_original_keys(fx_db):
    """批量查询：命中币种以调用方原始大小写返回，未命中币种不入 dict。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00697)
    repo.upsert_rate("USDGBP Curncy", "20260101", 1.2658)

    result = repo.get_rates_for_date(
        ["usdjpy curncy", "USDGBP Curncy", "USDAUD Curncy"], "20260101",
    )
    assert result["usdjpy curncy"] == pytest.approx(0.00697)
    assert result["USDGBP Curncy"] == pytest.approx(1.2658)
    assert "USDAUD Curncy" not in result


def test_get_recent_rate_bounded_no_future_leakage(fx_db):
    """有界回退：仅返回 ≤ 目标日期的最近值，绝不泄漏未来汇率。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00690)
    repo.upsert_rate("USDJPY Curncy", "20260301", 0.00800)

    assert repo.get_recent_rate("USDJPY Curncy", "20260215") == pytest.approx(0.00690)
    assert repo.get_recent_rate("USDJPY Curncy", "20260301") == pytest.approx(0.00800)
    assert repo.get_recent_rate("USDJPY Curncy", "20251231") is None


def test_upsert_rate_invalid_values_not_written(fx_db):
    """None/NaN/非正汇率不写入（降级回退值绝不污染真相源）。"""
    repo = _InMemoryFxRepo(fx_db)
    assert repo.upsert_rate("USDJPY Curncy", "20260101", None) == 0
    assert repo.upsert_rate("USDJPY Curncy", "20260101", float("nan")) == 0
    assert repo.upsert_rate("USDJPY Curncy", "20260101", 0.0) == 0
    assert repo.upsert_rate("USDJPY Curncy", "20260101", -0.00697) == 0
    assert fx_db.execute("SELECT COUNT(*) FROM fx_rates").fetchone()[0] == 0


def test_upsert_rate_idempotent_latest_wins(fx_db):
    """重复 upsert 同键：幂等 REPLACE，latest-wins。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00690)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00697, 143.5, source="bloomberg")
    assert repo.get_rate("USDJPY Curncy", "20260101") == pytest.approx(0.00697)
    # 存储键为规范化大写（_norm_ccy），直接 SQL 需用规范化键查询
    row = fx_db.execute(
        f"SELECT px_last, source FROM fx_rates WHERE ccy_ticker='{_JPY_NORM}'"
    ).fetchone()
    assert row[0] == pytest.approx(143.5)
    assert row[1] == "bloomberg"


def test_upsert_rates_dataframe_defaults_and_nan_filter(fx_db):
    """批量 DataFrame 写入：可选列缺省、NaN fx_rate 行跳过。

    注：fx_rate=1.0 为合法正值（真实 1:1 汇率），仓储不过滤；
    「排除旧版 1.0 兜底残留」由 seed 脚本负责。
    """
    repo = _InMemoryFxRepo(fx_db)
    df = pd.DataFrame([
        {"ccy_ticker": "USDJPY Curncy", "order_as_of_date": "20260101", "fx_rate": 0.00697},
        {"ccy_ticker": "USDGBP Curncy", "order_as_of_date": "20260101", "fx_rate": float("nan")},
        {"ccy_ticker": "USDAUD Curncy", "order_as_of_date": "20260101", "fx_rate": 1.0},
        {"ccy_ticker": "USDCAD Curncy", "order_as_of_date": "20260101",
         "fx_rate": 0.0074, "px_last": 135.0, "source": "fill_bdib_seed"},
    ])
    assert repo.upsert_rates(df) == 3  # 仅 NaN 行跳过
    assert repo.get_rate("USDJPY Curncy", "20260101") == pytest.approx(0.00697)
    row = fx_db.execute(
        f"SELECT px_last, source FROM fx_rates WHERE ccy_ticker='{_JPY_NORM}'"
    ).fetchone()
    assert row == (None, "bloomberg")  # 缺省 px_last=NULL / source='bloomberg'
    assert repo.get_rate("USDGBP Curncy", "20260101") is None
    assert repo.get_rate("USDAUD Curncy", "20260101") == 1.0
    row_cad = fx_db.execute(
        "SELECT px_last, source FROM fx_rates WHERE ccy_ticker='USDCAD CURNCY'"
    ).fetchone()
    assert row_cad[0] == pytest.approx(135.0)
    assert row_cad[1] == "fill_bdib_seed"


# ═══════════════════════════════════════════════════════════════════════
# Part 2: fx_fetcher 拉取链（repo 注入）
# ═══════════════════════════════════════════════════════════════════════


def test_table_hit_returns_cached_without_bloomberg_call(fx_db):
    """表精确命中：直接返回表值，零 Bloomberg 调用（即使未暂停）。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00697)

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=False), \
         patch("xbbg.blp.bdh") as mock_blp:
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260101", fx_repo=repo)
    assert result == pytest.approx(0.00697)
    mock_blp.assert_not_called()


def test_miss_fetches_bloomberg_and_persists(fx_db):
    """表 miss：拉取 Bloomberg → 返回换算值并落表（px_last 双存）。"""
    repo = _InMemoryFxRepo(fx_db)

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=False), \
         patch("xbbg.blp.bdh", return_value=pd.DataFrame({"px_last": [143.5]})):
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260101", fx_repo=repo)

    assert result == pytest.approx(1.0 / 143.5)
    assert repo.get_rate("USDJPY Curncy", "20260101") == pytest.approx(1.0 / 143.5)
    row = fx_db.execute(
        f"SELECT px_last, source FROM fx_rates WHERE ccy_ticker='{_JPY_NORM}'"
    ).fetchone()
    assert row[0] == pytest.approx(143.5)
    assert row[1] == "bloomberg"


def test_fetch_failure_degrades_to_bounded_table_recent(fx_db):
    """拉取空数据：降级到表内 ≤目标日期 最近值，且降级值不落表。"""
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00690)

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=False), \
         patch("xbbg.blp.bdh", return_value=pd.DataFrame()):
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260115", fx_repo=repo)

    assert result == pytest.approx(0.00690)  # 有界回退（非 1.0 兜底）
    # 降级值绝不落表：20260115 无行，20260101 原值不变
    assert repo.get_rate("USDJPY Curncy", "20260115") is None
    assert repo.get_rate("USDJPY Curncy", "20260101") == pytest.approx(0.00690)


def test_bounded_table_fallback_preferred_over_memory_cache(fx_db):
    """降级顺序：表有界回退优先于内存缓存（防未来汇率泄漏）。

    场景：内存缓存持有 6 月汇率（回填 1 月日期时属"未来"），
    表内有 1 月 1 日值 → 应返回表值而非内存值。
    """
    repo = _InMemoryFxRepo(fx_db)
    repo.upsert_rate("USDJPY Curncy", "20260101", 0.00690)
    fx_module._RECENT_RATES[_JPY_NORM] = 0.00900  # 模拟"未来"内存缓存

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=True):
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260115", fx_repo=repo)

    assert result == pytest.approx(0.00690)  # 表有界值，非内存的 0.009


def test_memory_cache_fallback_when_no_repo(fx_db):
    """无 repo 注入时降级到内存缓存（007 legacy 行为不变）。"""
    fx_module._RECENT_RATES[_JPY_NORM] = 0.00690

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=True):
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260115")

    assert result == pytest.approx(0.00690)


def test_full_degradation_chain_ends_at_one(fx_db):
    """表与内存均无回退值时，兜底 1.0。"""
    repo = _InMemoryFxRepo(fx_db)

    with patch("DataPipeline.acquisition.fx_fetcher.is_quota_paused", return_value=True):
        result = fetch_fx_rate_for_ccy("USDJPY Curncy", "20260115", fx_repo=repo)

    assert result == 1.0
