"""
Order Label Generation — order-level summary from processed EMSX fills.

Adapted from D:\\Evaluation\\src\\trading_data_processing\\fill.py:
  - generate_order_label()
  - generate_order_label_incremental()

Migrated from CostView/src/order_label.py (2026-05-11).

All functions use EMSX column names:
  - OrderId (not "Order Number")
  - StrategyType (not "Strategy Type")
  - TraderName (not "Trader Name")
  - FillShares (not "Exec Last Fill")
  - route_mkt_timestamp, mkt_timestamp (same)
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def generate_order_label(processed_fills: pd.DataFrame) -> pd.DataFrame:
    """Generate order-level summary labels from processed fills.

    Groups by OrderId and computes:
      - n_broker: number of distinct brokers
      - n_algo: number of distinct algo strategies
      - n_route: number of distinct routes (route_as_of_time)
      - n_fill: number of fills
      - currency, ccy_ticker, equ_ticker: first values
      - order_as_of_date: first date
      - total_amount: max Amount (order total)
      - total_fill: sum of FillShares
      - earliest_route_mkt_timestamp, latest_mkt_timestamp
      - volume_left, is_volume_left
    """
    logger.info("=== Generating order_label table ===")
    if processed_fills.empty:
        return pd.DataFrame()

    # Build aggregation dict based on available columns
    agg_dict = {}

    if "Broker" in processed_fills.columns:
        agg_dict["n_broker"] = ("Broker", "nunique")
    if "StrategyType" in processed_fills.columns:
        agg_dict["n_algo"] = ("StrategyType", "nunique")
    if "route_as_of_time" in processed_fills.columns:
        agg_dict["n_route"] = ("route_as_of_time", "nunique")
        agg_dict["n_fill"] = ("route_as_of_time", "count")
    elif "FillId" in processed_fills.columns:
        agg_dict["n_fill"] = ("FillId", "count")

    if "Currency" in processed_fills.columns:
        agg_dict["currency"] = ("Currency", "first")
    if "ccy_ticker" in processed_fills.columns:
        agg_dict["ccy_ticker"] = ("ccy_ticker", "first")
    if "equ_ticker" in processed_fills.columns:
        agg_dict["equ_ticker"] = ("equ_ticker", "first")
    if "order_as_of_date" in processed_fills.columns:
        agg_dict["order_as_of_date"] = ("order_as_of_date", "first")

    if "Amount" in processed_fills.columns:
        agg_dict["total_amount"] = ("Amount", "max")
    if "FillShares" in processed_fills.columns:
        agg_dict["total_fill"] = ("FillShares", "sum")

    if "route_mkt_timestamp" in processed_fills.columns:
        agg_dict["earliest_route_mkt_timestamp"] = ("route_mkt_timestamp", "min")
    if "mkt_timestamp" in processed_fills.columns:
        agg_dict["latest_mkt_timestamp"] = ("mkt_timestamp", "max")

    order_label = processed_fills.groupby("OrderId", as_index=False).agg(**agg_dict)

    # Compute volume_left and is_volume_left
    if "total_amount" in order_label.columns and "total_fill" in order_label.columns:
        order_label["total_amount"] = pd.to_numeric(order_label["total_amount"], errors="coerce")
        order_label["total_fill"] = pd.to_numeric(order_label["total_fill"], errors="coerce")
        order_label["volume_left"] = order_label["total_amount"] - order_label["total_fill"]
        order_label["is_volume_left"] = order_label["volume_left"] > 0
        order_label = order_label.drop(columns=["total_amount", "total_fill"])

    logger.info(f"Generated order labels for {len(order_label)} orders")
    return order_label


def generate_order_label_incremental(
    processed_fills: pd.DataFrame,
    existing_labels: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Incrementally generate order labels for new orders only.

    If existing_labels is provided, only processes orders not already in it.
    """
    logger.info("=== Incremental Generation: Order Labels ===")

    if processed_fills is None or processed_fills.empty:
        if existing_labels is not None and not existing_labels.empty:
            return existing_labels
        return pd.DataFrame()

    if existing_labels is not None and not existing_labels.empty:
        if "OrderId" not in existing_labels.columns:
            existing_labels = None

    if existing_labels is not None and not existing_labels.empty:
        existing_orders = set(existing_labels["OrderId"].astype(str))
        new_orders = set(processed_fills["OrderId"].astype(str)) - existing_orders

        if not new_orders:
            return existing_labels

        new_fills = processed_fills[
            processed_fills["OrderId"].astype(str).isin(new_orders)
        ]
        new_labels = generate_order_label(new_fills)
        updated_labels = pd.concat([existing_labels, new_labels], ignore_index=True)
    else:
        updated_labels = generate_order_label(processed_fills)

    return updated_labels
