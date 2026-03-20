# EMSX API Manual — Code Examples Reference

> Auto-generated mapping from EMSX API documentation to standalone Python test files.
>
> **Source documents:**
> - `docs/reference/EMSX-API-Quick-Reference.md`
> - `docs/reference/EMSX-API-Complete-Guide.md`
>
> **All files located in:** `doc/manual/`

---

## Table of Contents

1. [Session & Connection](#1-session--connection)
2. [Subscriptions](#2-subscriptions)
3. [Order Management](#3-order-management)
4. [Route Management](#4-route-management)
5. [Broker & Field Information](#5-broker--field-information)
6. [Fill & History](#6-fill--history)
7. [Sell-Side Operations](#7-sell-side-operations)
8. [Trading API Server (Identity)](#8-trading-api-server-identity)

---

## 1. Session & Connection

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `session_connect.py` | §1 Quick Start | Connecting to EMSX API | Synchronous and asynchronous Bloomberg session connection using `blpapi.SessionOptions` and `session.startAsync()`. Opens `//blp/emapisvc_beta` service. |

## 2. Subscriptions

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `subscriptions.py` | §3 Subscriptions | Subscriptions | Full order and route subscription example. Uses `SUBSCRIPTION_DATA` events with `EVENT_STATUS` codes (1=heartbeat, 4=initial paint, 6=new, 7=update, 8=delete, 11=end-of-paint). Creates separate order (`CorrelationId(98)`) and route (`CorrelationId(99)`) subscriptions with complete field lists via topic strings. |

## 3. Order Management

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `create_order.py` | §4.1 CreateOrder | Request/Response: CreateOrder | Creates a new order on the EMSX blotter. Sets EMSX_TICKER, EMSX_AMOUNT, EMSX_ORDER_TYPE, EMSX_TIF, EMSX_HAND_INSTRUCTION, EMSX_SIDE. |
| `create_order_and_route.py` | §4.2 CreateOrderAndRouteEx | Request/Response: CreateOrderAndRouteEx | Creates order and immediately routes to broker in a single request. Includes strategy parameters (VWAP) in comments. |
| `create_order_and_route_manually.py` | §4.3 CreateOrderAndRouteManually | Request/Response: CreateOrderAndRouteManually | Creates and routes manually (phone orders). Sets EMSX_BROKER="MANUAL" with manual route flag. |
| `modify_order.py` | §4.4 ModifyOrderEx | Request/Response: ModifyOrderEx | Modifies an existing order by EMSX_SEQUENCE. Note: `EMSX_LIMIT_PRICE=-99999` resets to 0 (for futures spreads). |
| `delete_order.py` | §4.5 DeleteOrder | Request/Response: DeleteOrder | Deletes orders from the blotter. Uses EMSX_SEQUENCE array for batch deletion. |
| `cancel_order.py` | §4.6 CancelOrderEx | Request/Response: CancelOrderEx | Cancels active orders. Uses EMSX_SEQUENCE array. |
| `assign_trader.py` | §4.7 AssignTrader | Request/Response: AssignTrader | Assigns a trader to an existing order by UUID. |
| `create_basket.py` | §4.8 CreateBasket | Request/Response: CreateBasket | Creates a named basket grouping multiple orders by EMSX_SEQUENCE numbers. |

## 4. Route Management

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `route.py` | §4.9 RouteEx | Request/Response: RouteEx | Routes an order to a broker with strategy parameters (VWAP with StartTime/EndTime/MaxPctVol/Style). |
| `route_manually.py` | §4.10 RouteManuallyEx | Request/Response: RouteManuallyEx | Routes manually for phone-based execution. |
| `modify_route.py` | §4.11 ModifyRouteEx | Request/Response: ModifyRouteEx | Modifies an existing route. Includes strategy parameters and multileg support in comments. |
| `cancel_route.py` | §4.12 CancelRouteEx | Request/Response: CancelRouteEx | Cancels active routes. Uses EMSX_SEQUENCE + EMSX_ROUTE_ID arrays. |
| `group_route.py` | §4.13 GroupRouteEx | Request/Response: GroupRouteEx | Routes multiple orders as a group to the same broker. Full source includes multileg/spread/strategy code in comments. |

## 5. Broker & Field Information

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `get_brokers.py` | §4.14 GetBrokersWithAssetClass | Request/Response: GetBrokersWithAssetClass | Lists available brokers for a given asset class (e.g., "EQTY"). |
| `get_broker_strategies.py` | §4.15 GetBrokerStrategiesWithAssetClass | Request/Response: GetBrokerStrategiesWithAssetClass | Lists broker strategies for a broker+asset class (e.g., BMTB + EQTY). |
| `get_broker_strategy_info.py` | §4.16 GetBrokerStrategyInfoWithAssetClass | Request/Response: GetBrokerStrategyInfoWithAssetClass | Gets strategy parameter details (FieldName, Disable flag, StringValue) for a specific strategy (e.g., VWAP). |
| `get_all_field_metadata.py` | §4.17 GetAllFieldMetaData | Request/Response: GetAllFieldMetaData | Retrieves metadata for all EMSX fields (EMSX_FIELD_NAME, EMSX_DISP_NAME, EMSX_TYPE, EMSX_LEVEL, EMSX_LEN). |
| `get_field_metadata.py` | §4.18 GetFieldMetaData | Request/Response: GetFieldMetaData | Retrieves metadata for specific fields using `appendValue()` to query multiple fields. |
| `get_asset_class.py` | §4.19 GetAssetClass | Request/Response: GetAssetClass | Gets asset class for a given ticker. Sets EMSX_TICKER, returns EMSX_ASSET_CLASS. |
| `get_teams.py` | §4.20 GetTeams | Request/Response: GetTeams | Returns TEAMS element listing available trading teams. |
| `get_trade_desks.py` | §4.21 GetTradeDesks | Request/Response: GetTradeDesks | AIM-only. Returns trade desks. Uses **production** endpoint `//blp/emapisvc`. |
| `get_traders.py` | §4.22 GetTraders | Request/Response: GetTraders | AIM-only. Returns traders. Uses **production** endpoint `//blp/emapisvc`. |

## 6. Fill & History

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `manual_fill.py` | §4.23 ManualFill | Request/Response: ManualFill | Submits manual fills for a route. Uses ROUTE_TO_FILL element with FILLS array, Legacy datetime choice. |
| `emsx_history.py` | §5 EMSXHistory | EMSXHistory | Retrieves historical fill data from `//blp/emsx.history.uat`. GetFills request with Scope/Filter (UUID or team), FromDateTime/ToDateTime. Handles PARTIAL_RESPONSE. Max 30-day range. |

## 7. Sell-Side Operations

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `sellside_ack.py` | §4.24 SellSideAck | Request/Response: SellSideAck | Sell-side acknowledgment of an order. Uses `request.append("EMSX_SEQUENCE", ...)`. Returns STATUS + MESSAGE. |
| `sellside_reject.py` | §4.25 SellSideReject | Request/Response: SellSideReject | Sell-side rejection of an order. Uses `request.append("EMSX_SEQUENCE", ...)`. Returns STATUS + MESSAGE. |

## 8. Trading API Server (Identity)

| File | Quick Ref Section | Complete Guide Section | Description |
|------|-------------------|----------------------|-------------|
| `user_identity.py` | §6 Trading API Server | User Identity Management | Server-side authentication via `//blp/apiauth`. Creates user identity with emrsId/ipAddress, handles AuthorizationSuccess/Failure, passes Identity to sendRequest/subscribe calls. |

---

## File Inventory (29 files)

```
doc/manual/
├── session_connect.py                  # Session & Connection
├── subscriptions.py                    # Order & Route Subscriptions
├── create_order.py                     # Order: Create
├── create_order_and_route.py           # Order: Create + Route
├── create_order_and_route_manually.py  # Order: Create + Route (Manual/Phone)
├── modify_order.py                     # Order: Modify
├── delete_order.py                     # Order: Delete
├── cancel_order.py                     # Order: Cancel
├── assign_trader.py                    # Order: Assign Trader
├── create_basket.py                    # Order: Create Basket
├── route.py                            # Route: Standard
├── route_manually.py                   # Route: Manual/Phone
├── modify_route.py                     # Route: Modify
├── cancel_route.py                     # Route: Cancel
├── group_route.py                      # Route: Group
├── get_brokers.py                      # Info: Brokers
├── get_broker_strategies.py            # Info: Broker Strategies
├── get_broker_strategy_info.py         # Info: Strategy Details
├── get_all_field_metadata.py           # Info: All Field Metadata
├── get_field_metadata.py               # Info: Specific Field Metadata
├── get_asset_class.py                  # Info: Asset Class
├── get_teams.py                        # Info: Teams
├── get_trade_desks.py                  # Info: Trade Desks (AIM-only)
├── get_traders.py                      # Info: Traders (AIM-only)
├── manual_fill.py                      # Fill: Manual
├── emsx_history.py                     # Fill: History Service
├── sellside_ack.py                     # Sell-Side: Acknowledge
├── sellside_reject.py                  # Sell-Side: Reject
└── user_identity.py                    # Server: User Identity/Auth
```

---

## Common Patterns

### Service Endpoints
| Endpoint | Usage |
|----------|-------|
| `//blp/emapisvc_beta` | UAT/Beta (most examples) |
| `//blp/emapisvc` | Production (GetTradeDesks, GetTraders — AIM-only) |
| `//blp/emsx.history.uat` | Historical fills (EMSXHistory) |
| `//blp/apiauth` | Authentication (Trading API Server) |

### Async Request/Response Pattern
All request/response files follow the same structure:
1. `SessionEventHandler` class with `processEvent` dispatcher
2. `processSessionStatusEvent` → starts async session
3. `processServiceStatusEvent` → creates and sends request
4. `processResponseEvent` → extracts response data
5. `main()` → configures session, starts async, waits on `bEnd` flag

### Subscription Pattern
`subscriptions.py` uses a different pattern:
- `SUBSCRIPTION_DATA` events instead of `RESPONSE`
- Topic string with field list (not `createRequest`)
- `CorrelationId` to distinguish order vs route messages
- `input()` wait instead of `bEnd` flag

### Key Notes
- `EMSX_LIMIT_PRICE = 0` → ignored; `-99999` → reset to 0 (for futures spreads)
- `EMSX_STOP_PRICE = -1` → clears stop price
- `EMSX_GTD_DATE = -1` → resets to DAY order
- Strategy parameters must be appended in correct order (per GetBrokerStrategyInfo)
- EMSXHistory supports max 30-day range
