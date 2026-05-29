"""Regime distribution query — read-only access to regime.db.

Phase 3: Uses ConnectionManagerProtocol instead of direct DataPipeline import.
"""

from __future__ import annotations

from typing import Any

from platform_data.contracts.protocols import ConnectionManagerProtocol


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
    if connection_manager is None:
        raise ValueError(
            "ConnectionManager must be provided to get_regime_distribution(). "
            "Import from DataPipeline: from DataPipeline import ConnectionManager"
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
