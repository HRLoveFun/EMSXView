"""BDIB 覆盖率监控 guard — 检测有成交但无 BDIB 行情的 ticker。

扫描 processed_fills.db 和 raw_bdib.db 的 equ_ticker 唯一值差集，
按 exchange 分组报告 ValidationViolation（ERROR 级别，仅告警不阻断）。

背景：549 个 ticker 有成交记录但无 BDIB 行情数据，主因是
BDIB_EXCHANGE 白名单遗漏 9 个交易所（424 个 ticker）和
ticker_repository 未注册（108 个 ticker）。该 guard 在 S5 前置校验中
运行，持续监控覆盖率缺口。

用法：
    guard = BDIBCoverageGuard()
    violations = guard.scan()
    if violations:
        for v in violations:
            logger.warning(v)
"""

from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set

from DataPipeline.config import Config
from DataPipeline.validation.enums import SeverityLevel, ViolationType
from DataPipeline.validation.violation import ValidationViolation

logger = logging.getLogger(__name__)


def _extract_exchange_from_ticker(ticker: str) -> str:
    """从 Bloomberg ticker 字符串中提取 exchange code。

    格式示例: "7203 JP Equity" → "JP"，"700 HK Equity" → "HK"。
    无法解析时返回 "UNKNOWN"。
    """
    parts = str(ticker).strip().split()
    if len(parts) >= 2:
        return parts[1].strip().upper()
    return "UNKNOWN"


class BDIBCoverageGuard:
    """BDIB 覆盖率检测器。

    对比 processed_fills 与 raw_bdib 的 equ_ticker 唯一值，
    找出有成交但无 BDIB 行情的 ticker，按 exchange 分组报告。
    """

    def __init__(
        self,
        processed_fills_db: Path | str | None = None,
        raw_bdib_db: Path | str | None = None,
    ) -> None:
        self._proc_db = Path(processed_fills_db) if processed_fills_db else Path(Config.PROCESSED_FILLS_DB)
        self._bdib_db = Path(raw_bdib_db) if raw_bdib_db else Path(Config.RAW_BDIB_DB)

    def _get_processed_tickers(self) -> Set[str]:
        """查询 processed_fills 的 DISTINCT equ_ticker。"""
        if not self._proc_db.exists():
            logger.debug("processed_fills.db 不存在，跳过覆盖率检测")
            return set()

        conn = sqlite3.connect(str(self._proc_db), timeout=30)
        try:
            rows = conn.execute(
                f"SELECT DISTINCT equ_ticker FROM {Config.PROCESSED_FILLS_TABLE} "
                f"WHERE equ_ticker IS NOT NULL AND TRIM(equ_ticker) != ''"
            ).fetchall()
            return {str(r[0]).strip() for r in rows}
        finally:
            conn.close()

    def _get_bdib_tickers(self) -> Set[str]:
        """查询 raw_bdib 的 DISTINCT equ_ticker。"""
        if not self._bdib_db.exists():
            logger.debug("raw_bdib.db 不存在，跳过覆盖率检测")
            return set()

        conn = sqlite3.connect(str(self._bdib_db), timeout=30)
        try:
            rows = conn.execute(
                f"SELECT DISTINCT equ_ticker FROM {Config.RAW_BDIB_TABLE} "
                f"WHERE equ_ticker IS NOT NULL AND TRIM(equ_ticker) != ''"
            ).fetchall()
            return {str(r[0]).strip() for r in rows}
        finally:
            conn.close()

    def scan(self, run_id: str = "coverage_check") -> List[ValidationViolation]:
        """扫描覆盖率缺口，返回违规列表。

        每条违规对应一个 exchange 分组，包含该 exchange 下缺失 BDIB 的
        ticker 数量和前 20 个 ticker 示例。
        """
        proc_tickers = self._get_processed_tickers()
        bdib_tickers = self._get_bdib_tickers()

        if not proc_tickers:
            return []

        # 差集：有成交但无 BDIB 行情的 ticker
        missing = proc_tickers - bdib_tickers
        if not missing:
            logger.info(
                "BDIB 覆盖率检测通过: %d 个 ticker 全部有 BDIB 行情",
                len(proc_tickers),
            )
            return []

        # 按 exchange 分组
        by_exchange: Dict[str, List[str]] = defaultdict(list)
        for ticker in missing:
            exchange = _extract_exchange_from_ticker(ticker)
            by_exchange[exchange].append(ticker)

        violations: List[ValidationViolation] = []

        for exchange, tickers in sorted(
            by_exchange.items(), key=lambda kv: -len(kv[1])
        ):
            violation = ValidationViolation(
                run_id=run_id,
                stage_name="S5_BDIB_CoverageCheck",
                field_name=f"raw_bdib.coverage.{exchange}",
                expected_constraint="processed_fills 中的 ticker 应在 raw_bdib 中有 BDIB 行情",
                actual_value={
                    "exchange": exchange,
                    "missing_ticker_count": len(tickers),
                    "sample_tickers": sorted(tickers)[:20],
                },
                severity=SeverityLevel.ERROR,
                violation_type=ViolationType.CUSTOM_CONSTRAINT,
                record_identifier=(
                    f"{len(tickers)} tickers with fills but no BDIB "
                    f"(exchange={exchange})"
                ),
            )
            violations.append(violation)

        logger.warning(
            "BDIB 覆盖率检测: %d 个 ticker 有成交但无 BDIB 行情，"
            "涉及 %d 个 exchange",
            len(missing),
            len(by_exchange),
        )

        return violations
