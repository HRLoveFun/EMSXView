"""Regime distribution query — read-only access to regime.db.

Phase 3: Uses ConnectionManagerProtocol instead of direct DataPipeline import.
"""

from __future__ import annotations

from typing import Any

from platform_data.contracts.protocols import ConnectionManagerProtocol


def get_latest_regime_date(
    connection_manager: ConnectionManagerProtocol | None = None,
) -> str | None:
    """返回当前 active 配置下 regime 标签的最新交易日（YYYY-MM-DD）。

    供前端在请求区间无数据时披露「数据截至哪一天」——regime 标签依赖上游
    pipeline 的独立分段，停更时区间查询会全空，但页面不应只显示
    “No data in range” 而不说明真实数据边界。
    库不存在 / 无 active 配置 / 无标签一律返回 None（fail-safe）。
    """
    if connection_manager is None:
        raise ValueError(
            "ConnectionManager must be provided to get_latest_regime_date(). "
            "Inject via data_access.ConnectionManager (data_access 为唯一只读数据入口)"
        )
    mgr = connection_manager
    if not mgr.database_exists("regime"):
        raise FileNotFoundError("regime.db not built yet")

    with mgr.connection("regime") as conn:
        cfg_row = conn.execute(
            "SELECT version_id FROM audit_regime_config_versions "
            "WHERE is_active=1 LIMIT 1"
        ).fetchone()
        if cfg_row is None or cfg_row[0] is None:
            return None
        row = conn.execute(
            "SELECT MAX(trade_date) FROM fill_regime_labels WHERE config_version = ?",
            (cfg_row[0],),
        ).fetchone()
        return str(row[0]) if row and row[0] else None


def get_regime_distribution(
    start_date: str,
    end_date: str,
    regime_dim: str = "vol_regime",
    connection_manager: ConnectionManagerProtocol | None = None,
) -> list[dict[str, Any]]:
    """Query regime distribution from regime.db.

    Returns a list of dicts with keys:
      date, market_code, low, normal, high, extreme, none_count, total,
      config_version

    Raises FileNotFoundError if regime.db does not exist.
    """
    # 防御深度：regime_dim 拼入 SQL 前必须过白名单（P2-3 整改，
    # 不再依赖调用方在 CostView/api/routers/costview.py 的前置校验）
    allowed_dims = {"vol_regime", "liq_regime", "trend_regime"}
    if regime_dim not in allowed_dims:
        raise ValueError(f"unsupported regime_dim: {regime_dim} (allowed: {sorted(allowed_dims)})")

    if connection_manager is None:
        raise ValueError(
            "ConnectionManager must be provided to get_regime_distribution(). "
            "Inject via data_access.ConnectionManager (data_access 为唯一只读数据入口)"
        )
    mgr = connection_manager

    if not mgr.database_exists("regime"):
        raise FileNotFoundError("regime.db not built yet")

    with mgr.connection("regime") as conn:
        cfg_row = conn.execute(
            "SELECT version_id FROM audit_regime_config_versions "
            "WHERE is_active=1 LIMIT 1"
        ).fetchone()
        cfg_version = cfg_row[0] if cfg_row else None
        if cfg_version is None:
            return []

        sql = f"""
            SELECT trade_date AS date, market_code,
                   COALESCE({regime_dim}, 'none') AS regime, COUNT(*) AS n
            FROM fill_regime_labels
            WHERE config_version = ?
              AND trade_date BETWEEN ? AND ?
            GROUP BY trade_date, market_code, COALESCE({regime_dim}, 'none')
            ORDER BY trade_date, market_code
        """
        cur = conn.execute(sql, (cfg_version, start_date, end_date))
        rows_raw = cur.fetchall()

    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for d, mc, regime, n in rows_raw:
        grouped.setdefault((d, mc), {})[str(regime)] = int(n)

    result: list[dict[str, Any]] = []
    for (d, mc), counts in grouped.items():
        total = sum(counts.values())
        result.append({
            "date": d,
            "market_code": mc,
            "low": counts.get("low", 0),
            "normal": counts.get("normal", 0),
            "high": counts.get("high", 0),
            "extreme": counts.get("extreme", 0),
            "none_count": counts.get("none", 0),
            "total": total,
            "config_version": cfg_version,
        })
    return result
