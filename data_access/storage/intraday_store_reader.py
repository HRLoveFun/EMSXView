"""盘中库只读适配器（057 DL-07 读侧 / DL-06 契约消费方）。

管道是盘中库唯一写入方（ADR-0016/0023）；本模块以 sqlite3 URI `mode=ro`
打开 `${DATA_DIR}/intraday/intraday_YYYYMMDD.db`，不建库、不写、不加锁升级。

降级纪律：文件不存在、表缺失、清单损坏一律返回空/None，由调用方经
`available()` 与 `freshness()` 显式呈现，不静默当最新（父计划 §4.0）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_access.config import Config, intraday_db_path
from platform_data.contracts import (
    INTRADAY_MANIFEST_FILE_NAME,
    TABLE_COLUMNS,
    DataFreshness,
    IntradayDatasetStatus,
    IntradayManifest,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    """解析 ISO 时间；无时区按 UTC，损坏返回 None（不猜）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class IntradayStoreReader:
    """按交易日读取盘中库与新鲜度清单（只读，任何 IO 失败降级为空）。"""

    def __init__(self, trade_date: str, data_dir: Path | None = None) -> None:
        self.trade_date = trade_date
        if data_dir is None:
            self.db_path = intraday_db_path(trade_date)
            self.manifest_path = Config.INTRADAY_MANIFEST_FILE
        else:
            root = Path(data_dir) / "intraday"
            self.db_path = root / f"intraday_{trade_date}.db"
            self.manifest_path = root / INTRADAY_MANIFEST_FILE_NAME

    # ── 可用性 ─────────────────────────────────────────────────────────
    def available(self) -> bool:
        return self.db_path.exists()

    def _connect(self) -> sqlite3.Connection | None:
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self.db_path.as_posix()}?mode=ro", uri=True, timeout=2.0
            )
        except sqlite3.Error:
            return None
        conn.row_factory = sqlite3.Row
        return conn

    def _rows(self, table: str, order_by: str = "") -> list[dict[str, Any]]:
        if table not in TABLE_COLUMNS:
            raise ValueError(f"unknown intraday table: {table}")
        conn = self._connect()
        if conn is None:
            return []
        try:
            sql = f"SELECT {', '.join(TABLE_COLUMNS[table])} FROM {table}"
            return [dict(r) for r in conn.execute(sql + (f" ORDER BY {order_by}" if order_by else ""))]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    # ── 数据集（列序与契约 TABLE_COLUMNS 一致） ────────────────────────
    def read_order_intents(self) -> list[dict[str, Any]]:
        return self._rows("order_intent", "order_key, valid_from")

    def read_snapshot_t0(self) -> list[dict[str, Any]]:
        return self._rows("snapshot_t0", "equ_ticker")

    def read_bars_t0(self) -> list[dict[str, Any]]:
        return self._rows("bars_10s_t0", "equ_ticker, mkt_timestamp")

    def read_bars_window(
        self, equ_ticker: str, start: str, end: str
    ) -> list[dict[str, Any]]:
        """区间 bar 查询（057 DL-30）：按 ticker 与时间窗过滤，避免全表读。

        时间戳为交易所本地 `HH:MM:SS`；区间左闭右开。文件/表缺失返回空。
        """
        conn = self._connect()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT equ_ticker, mkt_timestamp, open, high, low, close, volume "
                "FROM bars_10s_t0 "
                "WHERE equ_ticker = ? AND mkt_timestamp >= ? AND mkt_timestamp < ? "
                "ORDER BY mkt_timestamp",
                (equ_ticker, start, end),
            ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.Error:
            return []
        finally:
            conn.close()

    def read_intraday_fills(self) -> list[dict[str, Any]]:
        return self._rows("intraday_fills", "order_as_of_date, exchange_exec_time")

    def read_blotter_snapshots(self) -> list[dict[str, Any]]:
        return self._rows("blotter_snapshots", "export_ts")

    def read_route_params(self) -> list[dict[str, Any]]:
        return self._rows("route_params_snapshot", "as_of")

    # ── 新鲜度 ─────────────────────────────────────────────────────────
    def load_manifest(self) -> IntradayManifest | None:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        datasets = [
            IntradayDatasetStatus(
                dataset=str(entry.get("dataset", "")),
                as_of=str(entry.get("as_of", "")),
                watermark=str(entry.get("watermark", "")),
                row_count=int(entry.get("row_count") or 0),
                status=str(entry.get("status", "unknown")),
                last_error=entry.get("last_error"),
            )
            for entry in payload.get("datasets") or []
        ]
        return IntradayManifest(
            manifest_version=str(payload.get("manifest_version", "")),
            generated_at=str(payload.get("generated_at", "")),
            trade_date=str(payload.get("trade_date", self.trade_date)),
            datasets=datasets,
        )

    def freshness(self, now: datetime | None = None) -> list[DataFreshness]:
        """各数据集滞后分钟数；as_of 无法解析记 -1.0（显式未知，不填 0）。"""
        manifest = self.load_manifest()
        if manifest is None:
            return []
        reference = now or _utcnow()
        out: list[DataFreshness] = []
        for entry in manifest.datasets:
            as_of = _parse_iso(entry.as_of)
            lag = round((reference - as_of).total_seconds() / 60.0, 1) if as_of else -1.0
            out.append(DataFreshness(dataset=entry.dataset, as_of=entry.as_of, lag_minutes=lag))
        return out


__all__ = ["IntradayStoreReader"]
