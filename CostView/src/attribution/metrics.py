"""
Pure functions for attribution metrics. No I/O.

Conventions
-----------
- side: +1 for buy, -1 for sell
- All bps are SIGNED such that POSITIVE = ADVERSE TO THE TAKER:
    is_bps   = side * (fill_price / arrival_px - 1) * 1e4
    vwap_bps = side * (fill_price / interval_vwap - 1) * 1e4
- Reversal at +N min uses mid-price after the fill:
    reversal_Nm_bps = side * (mid_at_fill_plus_N - fill_price) / fill_price * 1e4
  Positive reversal = price moved adversely (kept going your way after you traded;
  i.e. you should have waited). Negative reversal = price reverted (good fill).
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np


def parse_side(raw: object) -> Optional[int]:
    """Map raw Side string ('B'/'S'/'BUY'/'SELL'/'BUY '/'sb') to +1/-1; None if unknown."""
    if raw is None:
        return None
    s = str(raw).strip().upper()
    if not s:
        return None
    if s.startswith("B"):
        return 1
    if s.startswith("S"):
        return -1
    return None


def slippage_bps(side: int, fill_price: float, benchmark: Optional[float]) -> Optional[float]:
    """Side-aware slippage in bps; positive = adverse. Returns None if benchmark is unusable."""
    if benchmark is None or not math.isfinite(benchmark) or benchmark <= 0:
        return None
    if not math.isfinite(fill_price) or fill_price <= 0:
        return None
    return float(side) * (fill_price / benchmark - 1.0) * 10000.0


def reversal_bps(side: int, fill_price: float, mid_after: Optional[float]) -> Optional[float]:
    """Side-aware reversal in bps; positive = price kept going your way (you over-paid in IS sense)."""
    if mid_after is None or not math.isfinite(mid_after) or mid_after <= 0:
        return None
    if not math.isfinite(fill_price) or fill_price <= 0:
        return None
    return float(side) * (mid_after - fill_price) / fill_price * 10000.0


def winsorize_series(values: np.ndarray, pct: float) -> np.ndarray:
    """Symmetric two-sided winsorization at +/- pct quantile. NaNs preserved."""
    if pct <= 0 or values.size == 0:
        return values
    finite = values[np.isfinite(values)]
    if finite.size < 5:
        return values
    lo = np.quantile(finite, pct)
    hi = np.quantile(finite, 1.0 - pct)
    out = values.copy()
    mask = np.isfinite(out)
    out[mask] = np.clip(out[mask], lo, hi)
    return out
