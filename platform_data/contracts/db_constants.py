"""Shared database table names and computational constants.

Extracted from platform_data/adapters/tca_bridge.py to break the
adapters.market → adapters.tca_bridge internal coupling (P1-4).

These constants are stable and are the single source of truth for table
names used by adapters that read from DataPipeline-managed SQLite databases.
"""

# ── Table names (synced with DataPipeline.config.Config) ──────────────────────

RAW_BDIB_TABLE: str = "raw_bdib"
BDIB_DAILY_SUMMARY_TABLE: str = "bdib_daily_summary"

# ── Computational constants ───────────────────────────────────────────────────

# Annualization factor for 10-second bars used in intraday realized vol.
# 252 (trading days) × 6.5 (hours/day) × 3600 (seconds/hour) ÷ 10 (bar-seconds)
# ≈ 589,680 bars per year
BARS_PER_YEAR: float = 252 * 6.5 * 3600 / 10
