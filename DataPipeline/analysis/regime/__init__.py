"""
Regime classification layer.

Sub-package responsibilities
----------------------------
- Read market reference (ref_market_mapping, ref_macro_event_*)
- Compute daily market features (daily_market_index)
- Classify daily regimes (vol / liquidity / trend) — parameterized by config_version
- Tag fills with regime labels (fill_regime_labels) — append-only

DDL: lives in ``DataPipeline/storage/schema/migrations/vN_to_vN+1.sql``.
Code constant ``schema.SCHEMA_VERSION`` MUST equal ``PRAGMA user_version`` after migrations.
"""
from __future__ import annotations

from .schema import SCHEMA_VERSION, REGIME_DB_PATH, create_all, ensure_schema_current

__all__ = ["SCHEMA_VERSION", "REGIME_DB_PATH", "create_all", "ensure_schema_current"]
