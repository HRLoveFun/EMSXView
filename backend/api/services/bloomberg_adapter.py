"""
Bloomberg EMSX Service — backward-compatible re-export facade.

P2-DUPE: This module is now a thin re-export wrapper that delegates to
``services.bloomberg.adapter`` (the canonical split-package facade).
All existing importers continue to work without changes.

Original God Class (2,738 lines) has been replaced by four single-responsibility
components under ``services/bloomberg/``:

    BloombergConnectionManager     — session lifecycle, pools, status
    EMSXSubscriptionEngine         — order/route subscription, cache, persist
    MarketDataEnrichmentService    — mktdata streaming, FX, round lot, permfail
    EMSXRequestHandler             — CRUD ops, broker/strategy queries

New code should import directly from the split package:
    from services.bloomberg.adapter import BloombergEMSXService, configure
"""

from __future__ import annotations

from services.bloomberg.adapter import (
    BloombergEMSXService,
    configure,
)

__all__ = ["BloombergEMSXService", "configure"]
