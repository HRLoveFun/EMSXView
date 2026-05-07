"""Data Platform cross-module contracts.

Defines the stable data types for triggering ingestion and querying
pipeline state. These are the only legal types for cross-module
communication about Data Platform operations.

Ownership:
  - Data Platform owns ingestion execution and pipeline state.
  - Consumers (CostView, ExecutionView) import types from this module.
  - No business logic, no DB imports — pure dataclasses and enums.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class PipelineState(Enum):
    """Enumeration of possible pipeline execution states."""
    IDLE = "idle"
    RUNNING = "running"
    FAILED = "failed"
    COMPLETED = "completed"
    PARTIAL = "partial"  # some dates succeeded, some failed


@dataclass(frozen=True)
class IngestionConfig:
    """Configuration for a data platform ingestion run.

    Attributes:
        start_date: First date to process (YYYYMMDD).
        end_date: Last date to process (YYYYMMDD), inclusive.
        parallel_sessions: Number of parallel Bloomberg sessions (default 1).
        force_reprocess: If True, bypass dedup and reprocess all dates.
        include_bdib: If True, include BDIB market data integration.
        include_daily_metrics: If True, pre-compute daily market metrics.
        team: Optional EMSX team scope (None = TradingSystem).
    """
    start_date: str
    end_date: str
    parallel_sessions: int = 1
    force_reprocess: bool = False
    include_bdib: bool = True
    include_daily_metrics: bool = True
    team: Optional[str] = None


@dataclass(frozen=True)
class IngestionResult:
    """Result of a data platform ingestion run.

    Attributes:
        dates_requested: All dates in the requested range.
        dates_processed: Dates that were successfully processed.
        dates_skipped: Dates skipped (duplicate, empty, or weekend).
        dates_failed: Dates that failed processing.
        rows_ingested: Total number of fill rows ingested.
        errors: List of error messages (one per failed date).
        pipeline_state: Final pipeline execution state.
    """
    dates_requested: list[str]
    dates_processed: list[str] = field(default_factory=list)
    dates_skipped: list[str] = field(default_factory=list)
    dates_failed: list[str] = field(default_factory=list)
    rows_ingested: int = 0
    errors: list[str] = field(default_factory=list)
    pipeline_state: PipelineState = PipelineState.COMPLETED



