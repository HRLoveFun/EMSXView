"""Bloomberg EMSX Service package.

Provides single-responsibility components:

    BloombergConnectionManager     — session lifecycle, request pools, status
    EMSXSubscriptionEngine         — order/route subscription, cache, persist
    MarketDataEnrichmentService    — mktdata streaming, FX, round lot, permfail
    EMSXRequestHandler             — CRUD ops, broker/strategy queries

For backward-compatible usage, import BloombergEMSXService directly from
``services.bloomberg_adapter``.
"""

__all__ = []
