"""Read-only convenience accessors for regime.db (M1 stub)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd

from CostView.src.regime.schema import REGIME_DB_PATH, connect


def get_fill_labels(
    date_iso: Optional[str] = None,
    market_code: Optional[str] = None,
    config_version: Optional[str] = None,
    db_path: Path = REGIME_DB_PATH,
) -> pd.DataFrame:
    where, params = [], []
    if date_iso:
        where.append("order_as_of_date_iso = ?"); params.append(date_iso)
    if market_code:
        where.append("market_code = ?"); params.append(market_code)
    if config_version:
        where.append("config_version = ?"); params.append(config_version)
    sql = "SELECT * FROM fill_regime_labels"
    if where:
        sql += " WHERE " + " AND ".join(where)
    conn = connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def get_daily_index(
    start: str, end: str,
    market_code: Optional[str] = None,
    db_path: Path = REGIME_DB_PATH,
) -> pd.DataFrame:
    sql = "SELECT * FROM daily_market_index WHERE trade_date BETWEEN ? AND ?"
    params = [start, end]
    if market_code:
        sql += " AND market_code = ?"
        params.append(market_code)
    conn = connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def get_audit_runs(
    stage_name: Optional[str] = None,
    limit: int = 50,
    db_path: Path = REGIME_DB_PATH,
) -> pd.DataFrame:
    sql = "SELECT * FROM audit_pipeline_runs"
    params = []
    if stage_name:
        sql += " WHERE stage_name = ?"
        params.append(stage_name)
    sql += " ORDER BY run_started_at DESC LIMIT ?"
    params.append(int(limit))
    conn = connect(db_path)
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
