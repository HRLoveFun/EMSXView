"""
Domain exception hierarchy for the EMSX platform.

Provides a structured, consistent exception taxonomy so that errors are
self-documenting, precisely catchable, and safely propagate across layers.

Hierarchy::

    EmsxError
    ├── DataError
    │   ├── DataNotFoundError
    │   ├── DataIntegrityError
    │   └── DataValidationError
    ├── PipelineError
    │   ├── StageExecutionError
    │   └── PipelineAbortError
    ├── StorageError
    │   ├── StorageConnectionError
    │   └── MigrationError
    ├── ConfigError
    │   ├── MissingConfigError
    │   └── InvalidConfigError
    ├── ApiError
    │   ├── AuthenticationError
    │   └── AuthorizationError
    └── ExternalServiceError
        ├── BloombergApiError
        └── NetworkError

Usage::

    from DataPipeline.src.common.exceptions import (
        DataNotFoundError,
        DataIntegrityError,
    )

    raise DataNotFoundError(f"No fill data for ticker={ticker}, date={date}")
    raise DataIntegrityError(f"Row count mismatch: hot={hot}, cold={cold}")
"""

from __future__ import annotations

from typing import Any


# ═══════════════════════════════════════════════════════════════════════════════
# Base Exception
# ═══════════════════════════════════════════════════════════════════════════════


class EmsxError(Exception):
    """Base exception for all EMSX platform errors.

    All domain exceptions should inherit from this class to enable
    top-level ``except EmsxError`` catching.
    """

    def __init__(self, message: str = "", detail: Any = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(self.message)

    def __str__(self) -> str:
        parts = [self.message]
        if self.detail is not None:
            parts.append(f"(detail={self.detail!r})")
        return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════════
# Data Errors
# ═══════════════════════════════════════════════════════════════════════════════


class DataError(EmsxError):
    """Base for data-related errors."""


class DataNotFoundError(DataError):
    """Raised when requested data does not exist.

    Example::

        raise DataNotFoundError("No fill data for ticker=AAPL, date=2026-04-15")
    """


class DataIntegrityError(DataError):
    """Raised when data fails integrity or consistency checks.

    Example::

        raise DataIntegrityError(
            "Row count mismatch between Hot and Cold storage"
        )
    """


class DataValidationError(DataError):
    """Raised when input data fails validation rules.

    Example::

        raise DataValidationError(
            "order_as_of_date must be in YYYY-MM-DD format"
        )
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Pipeline Errors
# ═══════════════════════════════════════════════════════════════════════════════


class PipelineError(EmsxError):
    """Base for data pipeline execution errors."""


class StageExecutionError(PipelineError):
    """Raised when a pipeline stage fails during execution.

    Example::

        raise StageExecutionError(
            "S2 (ProcessRawFills) failed: DB connection timeout"
        )
    """

    def __init__(self, stage: str = "", message: str = "") -> None:
        if not message:
            message = f"Pipeline stage failed"
            if stage:
                message += f": {stage}"
        super().__init__(message, detail={"stage": stage})


class PipelineAbortError(PipelineError):
    """Raised when the pipeline must be aborted (non-recoverable).

    Example::

        raise PipelineAbortError(
            "Critical data missing for S5 — aborting daily run"
        )
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Storage Errors
# ═══════════════════════════════════════════════════════════════════════════════


class StorageError(EmsxError):
    """Base for storage layer errors."""


class StorageConnectionError(StorageError):
    """Raised when a database or service connection fails.

    Example::

        raise StorageConnectionError("Cannot connect to raw_bdib.db at path=...")
    """


class MigrationError(StorageError):
    """Raised when a schema migration fails.

    Example::

        raise MigrationError("Migration 003_add_bdib_index failed: duplicate index")
    """


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration Errors
# ═══════════════════════════════════════════════════════════════════════════════


class ConfigError(EmsxError):
    """Base for configuration-related errors."""


class MissingConfigError(ConfigError):
    """Raised when a required configuration is missing.

    Example::

        raise MissingConfigError("Required env var BLOOMBERG_API_HOST not set")
    """

    def __init__(self, key: str = "", message: str = "") -> None:
        if not message:
            message = "Missing configuration"
            if key:
                message += f": {key}"
        super().__init__(message, detail={"key": key})


class InvalidConfigError(ConfigError):
    """Raised when a configuration value is invalid.

    Example::

        raise InvalidConfigError(
            "hot_window_raw_bdib must be > 0, got -5"
        )
    """


# ═══════════════════════════════════════════════════════════════════════════════
# API Errors
# ═══════════════════════════════════════════════════════════════════════════════


class ApiError(EmsxError):
    """Base for API-level errors (HTTP layer)."""


class AuthenticationError(ApiError):
    """Raised when authentication fails.

    Example::

        raise AuthenticationError("Invalid API token")
    """


class AuthorizationError(ApiError):
    """Raised when the authenticated user lacks permission.

    Example::

        raise AuthorizationError("User lacks permission to modify routes")
    """


# ═══════════════════════════════════════════════════════════════════════════════
# External Service Errors
# ═══════════════════════════════════════════════════════════════════════════════


class ExternalServiceError(EmsxError):
    """Base for errors from external services (Bloomberg, market data, etc.)."""


class BloombergApiError(ExternalServiceError):
    """Raised when a Bloomberg API call fails.

    Example::

        raise BloombergApiError("blp.bdh AAPL US Equity failed: connection refused")
    """


class NetworkError(ExternalServiceError):
    """Raised when a network operation fails.

    Example::

        raise NetworkError("Connection timeout after 30s to bloomberg.bpipe.com")
    """
