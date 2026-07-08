"""raw_bdib 空 bar 检测器 — 在 BDIB 集成前检查是否存在完全空 bar。

检测条件：
- OHLC (open/high/low/close) 全部为 NULL
- volume 为 0 或 NULL
- value 为 0 或 NULL

历史：早期写入路径曾产生 28,591 行完全空 bar（集中在 2026-04-08），
已于 2026-07-07 通过 scripts/ops/cleanup_raw_bdib_empty_bars.py 清理。
当前 _validate_bdib_response 已能过滤，不会再产生新的空 bar。

该模块作为 IntegrateBDIBStage (S5) 的前置校验运行：
- 检测到空 bar → 记录 ValidationViolation (ERROR 级别)
- 默认行为：告警但不阻断（由 GuardPipeline 按阶段策略决定）

用法：
    guard = EmptyBarGuard(db_path=Config.RAW_BDIB_DB)
    violations = guard.scan()
    if violations:
        for v in violations:
            logger.warning(v)
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import List

from DataPipeline.config import Config
from DataPipeline.validation.enums import SeverityLevel, ViolationType
from DataPipeline.validation.violation import ValidationViolation

logger = logging.getLogger(__name__)


class EmptyBarGuard:
    """raw_bdib 空 bar 检测器。

    扫描 raw_bdib 表，检测 OHLC 全 NULL + volume=0 + value=0 的行。
    此类行不包含任何有效市场数据，不应进入下游集成流程。
    """

    def __init__(self, db_path: Path | str | None = None):
        self._db_path = Path(db_path) if db_path else Path(Config.RAW_BDIB_DB)

    def scan(self, run_id: str = "pre_check") -> List[ValidationViolation]:
        """扫描 raw_bdib 表，返回空 bar 违规列表。"""
        if not self._db_path.exists():
            logger.info("raw_bdib.db 不存在，跳过空 bar 检测")
            return []

        violations: List[ValidationViolation] = []
        conn = sqlite3.connect(str(self._db_path))
        try:
            # 统计空 bar 行数
            empty_count = conn.execute(
                f"""SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}
                    WHERE open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL
                      AND (volume IS NULL OR volume = 0)
                      AND (value IS NULL OR value = 0)"""
            ).fetchone()[0]

            if empty_count == 0:
                logger.info("raw_bdib 空 bar 检测通过：未发现空行")
                return violations

            # 获取空 bar 涉及的日期
            dates = [
                r[0] for r in conn.execute(
                    f"""SELECT DISTINCT order_as_of_date
                        FROM {Config.RAW_BDIB_TABLE}
                        WHERE open IS NULL"""
                ).fetchall()
            ]

            # 获取涉及的 ticker 数量
            ticker_count = conn.execute(
                f"""SELECT COUNT(DISTINCT equ_ticker)
                    FROM {Config.RAW_BDIB_TABLE}
                    WHERE open IS NULL"""
            ).fetchone()[0]

            # 记录一条汇总违规（而非逐行 28,591 条）
            violation = ValidationViolation(
                run_id=run_id,
                stage_name="S5_BDIB_EmptyBarCheck",
                field_name="raw_bdib.empty_bars",
                expected_constraint="OHLC NOT NULL OR volume > 0",
                actual_value={
                    "empty_bar_count": empty_count,
                    "affected_dates": dates[:20],  # 最多展示 20 个日期
                    "affected_ticker_count": ticker_count,
                },
                severity=SeverityLevel.ERROR,
                violation_type=ViolationType.CUSTOM_CONSTRAINT,
                record_identifier=f"{empty_count} empty bars across {len(dates)} dates, {ticker_count} tickers",
            )
            violations.append(violation)

            logger.warning(
                "raw_bdib 空 bar 检测: 发现 %s 行完全空 bar, 涉及 %d 个日期, %d 个 ticker",
                f"{empty_count:,}", len(dates), ticker_count,
            )

        finally:
            conn.close()

        return violations

    def auto_cleanup(self, run_id: str = "auto_cleanup") -> List[ValidationViolation]:
        """检测并自动清理空 bar 行。

        仅在单日空 bar 数 < 10,000 且磁盘空间 > 100MB 时自动清理，
        否则仅告警。返回违规列表（清理后为空表示成功）。
        """
        if not self._db_path.exists():
            return []

        conn = sqlite3.connect(str(self._db_path))
        try:
            empty_count = conn.execute(
                f"""SELECT COUNT(*) FROM {Config.RAW_BDIB_TABLE}
                    WHERE open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL
                      AND (volume IS NULL OR volume = 0)
                      AND (value IS NULL OR value = 0)"""
            ).fetchone()[0]

            if empty_count == 0:
                return []

            # 检查磁盘空间
            try:
                import shutil
                disk_free = shutil.disk_usage(self._db_path.parent).free / (1024 * 1024)
            except Exception:
                disk_free = 9999  # 无法检查时不阻止清理

            if empty_count > 10_000:
                logger.warning(
                    "空 bar 数量 %s 超过自动清理阈值 (10,000)，仅告警不清理",
                    f"{empty_count:,}",
                )
                return self.scan(run_id)

            if disk_free < 200:
                logger.warning("磁盘空间不足 (%.0f MB)，跳过自动清理", disk_free)
                return self.scan(run_id)

            # 执行清理
            conn.execute(
                f"""DELETE FROM {Config.RAW_BDIB_TABLE}
                    WHERE open IS NULL AND high IS NULL AND low IS NULL AND close IS NULL
                      AND (volume IS NULL OR volume = 0)
                      AND (value IS NULL OR value = 0)"""
            )
            conn.commit()
            logger.info("自动清理 %s 行空 bar", f"{empty_count:,}")

            return []
        finally:
            conn.close()
