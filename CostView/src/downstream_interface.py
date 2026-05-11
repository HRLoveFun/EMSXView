"""
Downstream Interface — formal contract between CostView and MarketFetch.

Provides:
    - Ticker registry queries (active equity/currency tickers)
    - Date-level ticker lookup for market data fetching
    - Diff computation for unfetched ticker-date pairs
    - Manifest writer for file-based notification to downstream consumers

MarketFetch (when implemented) watches market_fetch_manifest.json for changes,
reads registry tables for the full ticker list, and fetches BDIB/market data
for new/updated ticker-date combinations.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from DataPipeline.src.storage.repositories.fills_read import SqliteFillReadRepository
from DataPipeline.src.common.outdated_tickers import load_outdated_ticker_set
from DataPipeline.src.common.processing_config import ProcessingConfig as Config

logger = logging.getLogger(__name__)


def _filter_outdated_equ_tickers(tickers: List[str]) -> List[str]:
    outdated = load_outdated_ticker_set()
    if not outdated:
        return tickers
    return [ticker for ticker in tickers if ticker not in outdated]


def get_active_tickers(
    ticker_type: str = "all",
    fills_repo: Optional[SqliteFillReadRepository] = None,
) -> List[str]:
    """Return current ticker registry entries."""
    if fills_repo is None:
        fills_repo = SqliteFillReadRepository()

    tickers: List[str] = []

    if ticker_type in ("equ", "all"):
        equ_df = fills_repo.get_equ_ticker_registry()
        if not equ_df.empty:
            tickers.extend(_filter_outdated_equ_tickers(equ_df["equ_ticker"].tolist()))

    if ticker_type in ("ccy", "all"):
        ccy_df = fills_repo.get_ccy_ticker_registry()
        if not ccy_df.empty:
            tickers.extend(ccy_df["ccy_ticker"].tolist())

    return tickers


def get_tickers_for_date(
    date_str: str,
    fills_repo: Optional[SqliteFillReadRepository] = None,
) -> Dict[str, List[str]]:
    """Return equity and currency tickers active on a specific date."""
    if fills_repo is None:
        fills_repo = SqliteFillReadRepository()

    result: Dict[str, List[str]] = {"equ": [], "ccy": []}

    equ_map = fills_repo.get_ticker_dates("equ_ticker")
    outdated = load_outdated_ticker_set()
    for ticker, dates in equ_map.items():
        if ticker not in outdated and date_str in dates:
            result["equ"].append(ticker)

    ccy_map = fills_repo.get_ticker_dates("ccy_ticker")
    for ticker, dates in ccy_map.items():
        if date_str in dates:
            result["ccy"].append(ticker)

    return result


def get_unfetched_ticker_dates(
    fetched_set: Set[Tuple[str, str]],
    fills_repo: Optional[SqliteFillReadRepository] = None,
) -> List[Tuple[str, str]]:
    """Compute ticker-date pairs that haven't been fetched by MarketFetch."""
    if fills_repo is None:
        fills_repo = SqliteFillReadRepository()

    all_pairs: List[Tuple[str, str]] = []
    outdated = load_outdated_ticker_set()

    for ticker_type in ("equ_ticker", "ccy_ticker"):
        ticker_map = fills_repo.get_ticker_dates(ticker_type)
        for ticker, dates in ticker_map.items():
            if ticker_type == "equ_ticker" and ticker in outdated:
                continue
            for date_str in dates:
                pair = (ticker, date_str)
                if pair not in fetched_set:
                    all_pairs.append(pair)

    return all_pairs


def write_manifest(
    fills_repo: Optional[SqliteFillReadRepository] = None,
    updated_dates: Optional[List[str]] = None,
    new_tickers: Optional[List[str]] = None,
) -> Path:
    """Write the market_fetch_manifest.json for downstream consumers."""
    if fills_repo is None:
        fills_repo = SqliteFillReadRepository()

    equ_tickers = get_active_tickers("equ", fills_repo)
    ccy_tickers = get_active_tickers("ccy", fills_repo)

    manifest: Dict[str, Any] = {
        "last_updated": datetime.now().isoformat(),
        "new_tickers": new_tickers or [],
        "updated_dates": updated_dates or [],
        "equ_tickers": equ_tickers,
        "ccy_tickers": ccy_tickers,
        "equ_ticker_count": len(equ_tickers),
        "ccy_ticker_count": len(ccy_tickers),
        "processed_fills_db": str(Config.PROCESSED_FILLS_DB),
    }

    manifest_path = Config.MARKET_FETCH_MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, default=str),
        encoding="utf-8",
    )

    logger.info(
        f"Manifest written: {manifest_path} "
        f"({len(equ_tickers)} equ, {len(ccy_tickers)} ccy tickers)"
    )
    return manifest_path
