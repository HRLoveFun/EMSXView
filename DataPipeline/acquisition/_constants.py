"""
Shared Bloomberg EMSX constants — single source of truth for blpapi.Name
objects and field definitions used across acquisition modules.

Usage:
    from DataPipeline.acquisition._constants import (
        GET_FILLS_RESPONSE,
        EXPECTED_FILL_COLUMNS,
    )
"""

from __future__ import annotations

from typing import List

import blpapi

# ═══════════════════════════════════════════════════════════════════════════
# blpapi.Name constants — used for message type matching in event processing
# ═══════════════════════════════════════════════════════════════════════════

GET_FILLS_RESPONSE = blpapi.Name("GetFillsResponse")
"""Message type for EMSX GetFills responses."""

ERROR_INFO = blpapi.Name("ErrorInfo")
"""Message type for EMSX error information."""

# ═══════════════════════════════════════════════════════════════════════════
# Fill field definitions
# ═══════════════════════════════════════════════════════════════════════════
#
# All known fill fields from Bloomberg EMSX History API (from Bloomberg
# documentation). Maps field name -> expected blpapi getter method name.

EXPECTED_FILL_COLUMNS: List[str] = [
    "Account", "Amount", "AssetClass", "BasketId", "BBGID", "BlockId",
    "Broker", "ClearingAccount", "ClearingFirm", "ContractExpDate",
    "CorrectedFillId", "Currency", "Cusip", "DateTimeOfFill", "Exchange",
    "ExecPrevSeqNo", "ExecType", "ExecutingBroker", "FillId", "FillPrice",
    "FillShares", "InvestorID", "IsCfd", "Isin", "IsLeg", "LastCapacity",
    "LastMarket", "LimitPrice", "Liquidity", "LocalExchangeSymbol",
    "LocateBroker", "LocateId", "LocateRequired", "MultilegId", "OCCSymbol",
    "OrderExecutionInstruction", "OrderHandlingInstruction", "OrderId",
    "OrderInstruction", "OrderOrigin", "OrderReferenceId",
    "OriginatingTraderUuid", "ReroutedBroker", "RouteCommissionAmount",
    "RouteCommissionRate", "RouteExecutionInstruction",
    "RouteHandlingInstruction", "RouteId", "RouteNetMoney", "RouteNotes",
    "RouteShares", "SecurityName", "Sedol", "SettlementDate", "Side",
    "StopPrice", "StrategyType", "Ticker", "TIF", "TraderName",
    "TraderUuid", "Type", "UserCommissionAmount", "UserCommissionRate",
    "UserFees", "UserNetMoney", "YellowKey",
]

FILL_FIELD_EXTRACTORS: dict[str, str] = {
    "OrderId":                   "getValueAsInteger",
    "Account":                   "getValueAsString",
    "SecurityName":              "getValueAsString",
    "Ticker":                    "getValueAsString",
    "Exchange":                  "getValueAsString",
    "Currency":                  "getValueAsString",
    "Side":                      "getValueAsString",
    "Amount":                    "getValueAsFloat",
    "NyOrderCreateAsOfDateTime": "getValueAsString",
    "Type":                      "getValueAsString",
    "LimitPrice":                "getValueAsFloat",
    "StopPrice":                 "GetValueAsFloat",
    "Broker":                    "getValueAsString",
    "StrategyType":              "getValueAsString",
    "TraderName":                "getValueAsString",
    "TraderUuid":                "getValueAsInteger",
    "RouteId":                   "getValueAsInteger",
    "NyTranCreateAsOfDateTime":  "getValueAsString",
    "RouteShares":               "getValueAsFloat",
    "FillId":                    "getValueAsInteger",
    "ExecType":                  "getValueAsString",
    "DateTimeOfFill":            "getValueAsString",
    "FillPrice":                 "getValueAsFloat",
    "FillShares":                "getValueAsFloat",
    "LastCapacity":              "getValueAsString",
    "LastMarket":                "getValueAsString",
    "Liquidity":                 "getValueAsString",
    "LocalExchangeSymbol":       "getValueAsString",
}
