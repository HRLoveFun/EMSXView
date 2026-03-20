# EMSX API Quick Reference

> **Start here for rapid development.** For detailed examples and comprehensive documentation, see the [EMSX API Complete Guide](EMSX-API-Complete-Guide.md).
>
> **Quick Navigation:** [Quick Start](#1-quick-start) | [API Requests](#4-api-requests-reference) | [Field Reference](#5-field-reference) | [FAQ](#7-frequently-asked-questions) | [Index](#8-index)

---

## Table of Contents

- [1. Quick Start](#1-quick-start)
  - [1.1 TL;DR - Get Connected in 5 Minutes](#11-tldr---get-connected-in-5-minutes)
  - [1.2 Environment Setup](#12-environment-setup)
  - [1.3 Connection Endpoints](#13-connection-endpoints)
- [2. Core Concepts](#2-core-concepts)
  - [2.1 Session & Service Model](#21-session--service-model)
  - [2.2 Request/Response vs Subscription](#22-requestresponse-vs-subscription)
  - [2.3 Event Types](#23-event-types)
  - [2.4 Correlation IDs](#24-correlation-ids)
- [3. Working with Subscriptions](#3-working-with-subscriptions)
  - [3.1 Subscription Basics](#31-subscription-basics)
  - [3.2 Event Status Codes](#32-event-status-codes)
  - [3.3 Order & Route Status](#33-order--route-status)
- [4. API Requests Reference](#4-api-requests-reference)
  - [4.1 Order Management](#41-order-management)
  - [4.2 Route Management](#42-route-management)
  - [4.3 Basket Operations](#43-basket-operations)
  - [4.4 Broker & Strategy Info](#44-broker--strategy-info)
  - [4.5 Administrative](#45-administrative)
- [5. Field Reference](#5-field-reference)
  - [5.1 Essential Fields](#51-essential-fields)
  - [5.2 Order Fields](#52-order-fields)
  - [5.3 Route Fields](#53-route-fields)
  - [5.4 Special Fields](#54-special-fields)
- [6. Trading API Server](#6-trading-api-server)
  - [6.1 Server vs Desktop API](#61-server-vs-desktop-api)
  - [6.2 User Identity Management](#62-user-identity-management)
- [7. Frequently Asked Questions](#7-frequently-asked-questions)
- [8. Index](#8-index)

---

## 1. Quick Start

### 1.1 TL;DR - Get Connected in 5 Minutes

**Prerequisites:**
- Bloomberg terminal access (DAPI) or Trading API Server deployment
- Python/Java/.NET/C++ Bloomberg API library installed
- EMSX API access enabled by Bloomberg Trade Desk

> **Detailed Setup:** See [Establishing the Connection](EMSX-API-Complete-Guide.md#establishing-the-connection) in the Complete Guide for synchronous/asynchronous patterns and error handling.

**Quick Connect (Python):**

```python
import blpapi

# Configuration
SERVICE = "//blp/emapisvc_beta"  # Use //blp/emapisvc for Production
HOST = "localhost"
PORT = 8194

# 1. Create session
sessionOptions = blpapi.SessionOptions()
sessionOptions.setServerHost(HOST)
sessionOptions.setServerPort(PORT)
session = blpapi.Session(sessionOptions)

# 2. Start session (synchronous)
if not session.start():
    raise Exception("Failed to start session")

# 3. Open service
if not session.openService(SERVICE):
    raise Exception("Failed to open service")

# 4. Create and send request
service = session.getService(SERVICE)
request = service.createRequest("CreateOrder")
request.set("EMSX_TICKER", "IBM US Equity")
request.set("EMSX_AMOUNT", 1000)
request.set("EMSX_ORDER_TYPE", "MKT")
request.set("EMSX_TIF", "DAY")
request.set("EMSX_HAND_INSTRUCTION", "ANY")
request.set("EMSX_SIDE", "BUY")

session.sendRequest(request)

# 5. Process response
event = session.nextEvent(5000)  # 5 second timeout
for msg in event:
    print(msg)
```

### 1.2 Environment Setup

| Component | UAT/Beta | Production |
|-----------|----------|------------|
| Service Name | `//blp/emapisvc_beta` | `//blp/emapisvc` |
| Terminal Access | UAT ON<GO> | Standard EMSX<GO> |
| Test Brokers | BB, BMTB, EFIX, API | Broker-specific |
| Host | localhost | Trading API Server IP |
| Default Port | 8194 | 8194 |

> **Full Environment Details:** See [Opening the Service](EMSX-API-Complete-Guide.md#opening-the-service) in the Complete Guide for endpoint configuration and service schema details.

### 1.3 Connection Endpoints

**Desktop API (DAPI):**
- Runs on machine with logged-in Bloomberg terminal
- Host: `localhost`
- Uses terminal's user identity automatically
- See [Creating a Session](EMSX-API-Complete-Guide.md#creating-a-session) for DAPI-specific setup

**Trading API Server:**
- Runs on server infrastructure
- Host: Server IP address
- Requires explicit user identity creation
- Supports multiple simultaneous user identities
- See [Trading API Server](EMSX-API-Complete-Guide.md#trading-api-server) section for full implementation

---

## 2. Core Concepts

### 2.1 Session & Service Model

The EMSX API follows Bloomberg's session-service architecture:

```
┌─────────────────────────────────────────────────────────┐
│                    APPLICATION                          │
├─────────────────────────────────────────────────────────┤
│  Session (connection to Bloomberg)                      │
│  └── Service (EMSX API capabilities)                    │
│      ├── Requests (order actions)                       │
│      └── Subscriptions (real-time blotter data)         │
└─────────────────────────────────────────────────────────┘
```

**Key Points:**
- One session can host multiple services
- EMSX service provides request/response AND subscription capabilities
- Session handles connection management and failover

> **Architecture Deep Dive:** See [Sessions and Services](EMSX-API-Complete-Guide.md#sessions-and-services) in the Complete Guide for schema details and service capabilities.

### 2.2 Request/Response vs Subscription

| Paradigm | Purpose | Example |
|----------|---------|---------|
| **Request/Response** | One-time actions | CreateOrder, CancelRoute |
| **Subscription** | Real-time data feed | Order blotter, Route updates |

**Subscription Model (CRUD-based):**
- **C**reate (EVENT_STATUS=6): New order/route created
- **R**ead (EVENT_STATUS=4): Initial paint (snapshot)
- **U**pdate (EVENT_STATUS=7): Field changes
- **D**elete (EVENT_STATUS=8): Order removed from blotter

> **Paradigm Details:** See [Request/Response and Subscriptions](EMSX-API-Complete-Guide.md#requestresponse-and-subscriptions) in the Complete Guide for workflow patterns and best practices.

### 2.3 Event Types

| Event Type | Description |
|------------|-------------|
| `SESSION_STATUS` | Connection status (started, terminated, etc.) |
| `SERVICE_STATUS` | Service open/close events |
| `SUBSCRIPTION_STATUS` | Subscription success/failure |
| `SUBSCRIPTION_DATA` | Real-time order/route updates |
| `RESPONSE` | Request response (final) |
| `PARTIAL_RESPONSE` | Request response (chunked) |
| `ADMIN` | Queue warnings, slow consumer alerts |

> **Event Handling:** See [Events](EMSX-API-Complete-Guide.md#events) in the Complete Guide for detailed event processing and workflow triggers.

### 2.4 Correlation IDs

Correlation IDs link requests to responses:

```python
# Create request with correlation ID
requestID = blpapi.CorrelationId()
session.sendRequest(request, correlationId=requestID)

# Match response
event = session.nextEvent()
for msg in event:
    if msg.correlationIds()[0].value() == requestID.value():
        # This is our response
        processResponse(msg)
```

---

## 3. Working with Subscriptions

### 3.1 Subscription Basics

**Two Required Subscriptions:**
1. **Order Subscription** - Parent orders blotter
2. **Route Subscription** - Child routes (placements) blotter

```python
# Order subscription topic
orderTopic = "//blp/emapisvc_beta/order?fields=" + \
    "API_SEQ_NUM,EMSX_SEQUENCE,EMSX_STATUS,EMSX_TICKER," + \
    "EMSX_AMOUNT,EMSX_FILLED,EMSX_SIDE,EMSX_ORDER_TYPE"

# Route subscription topic  
routeTopic = "//blp/emapisvc_beta/route?fields=" + \
    "API_SEQ_NUM,EMSX_SEQUENCE,EMSX_ROUTE_ID,EMSX_STATUS," + \
    "EMSX_BROKER,EMSX_AMOUNT,EMSX_FILLED"

# Subscribe
subscriptions = blpapi.SubscriptionList()
subscriptions.add(topic=orderTopic, correlationId=orderSubID)
subscriptions.add(topic=routeTopic, correlationId=routeSubID)
session.subscribe(subscriptions)
```

> **Full Subscription Guide:** See [Using Subscriptions](EMSX-API-Complete-Guide.md#using-subscriptions) in the Complete Guide for topic syntax, field selection, and CRUD event handling.

### 3.2 Event Status Codes

| Code | Type | Description |
|------|------|-------------|
| 1 | Heartbeat | Sent every second; indicates connection health |
| 4 | Initial Paint | Snapshot of existing orders/routes |
| 6 | New | New order/route created |
| 7 | Update | Field value changed |
| 8 | Delete | Order/route removed from blotter |
| 11 | End Initial Paint | All snapshot data sent |

> **Event Status Details:** See [Event Status](EMSX-API-Complete-Guide.md#event-status) in the Complete Guide for handling each event type.

### 3.3 Order & Route Status

**Order Status Values:**

| Status | Meaning |
|--------|---------|
| `NEW` | Staged, no routes created |
| `SENT` | First route sent to broker |
| `WORKING` | Route acknowledged by broker |
| `PARTFILLED` | Partial fills received |
| `FILLED` | All shares filled |
| `CANCEL` | Order cancelled |
| `ASSIGN` | All routes cancelled, no fills |

**Route Status Values:**

| Status | Meaning |
|--------|---------|
| `SENT` | Route sent to broker |
| `WORKING` | Broker acknowledged |
| `PARTFILLED` | Partially filled |
| `FILLED` | Completely filled |
| `CANCEL` | Cancelled |
| `REJECTED` | Rejected by broker |
| `CXLREQ` | Cancel requested |

---

## 4. API Requests Reference

> **Complete Request Documentation:** See [Reference - Requests](EMSX-API-Complete-Guide.md#reference---requests) in the Complete Guide for 25+ full code examples including all optional parameters and response handling.

### 4.1 Order Management

#### CreateOrder
Creates a new parent order (staged, not routed).

**Mandatory Fields:**
- `EMSX_TICKER` - Security (e.g., "IBM US Equity")
- `EMSX_AMOUNT` - Quantity
- `EMSX_ORDER_TYPE` - MKT, LMT, STP, STP_LMT
- `EMSX_TIF` - DAY, GTC, GTD, etc.
- `EMSX_HAND_INSTRUCTION` - ANY, DMA, etc.
- `EMSX_SIDE` - BUY, SELL, SELL_SHORT

**Example:**
```python
request = service.createRequest("CreateOrder")
request.set("EMSX_TICKER", "MSFT US Equity")
request.set("EMSX_AMOUNT", 7000)
request.set("EMSX_ORDER_TYPE", "MKT")
request.set("EMSX_TIF", "DAY")
request.set("EMSX_HAND_INSTRUCTION", "ANY")
request.set("EMSX_SIDE", "BUY")
# Optional: EMSX_LIMIT_PRICE, EMSX_ACCOUNT, EMSX_BASKET_NAME, etc.
```

> **Full Example:** See [CreateOrder](EMSX-API-Complete-Guide.md#createorder) in the Complete Guide for all optional fields and response handling.

#### ModifyOrderEx
Modifies an existing order.

**Key Fields:**
- `EMSX_SEQUENCE` - Order number
- `EMSX_AMOUNT` - New quantity
- `EMSX_ORDER_TYPE` - New order type
- `EMSX_LIMIT_PRICE` - Use -99999 to reset to 0
- `EMSX_STOP_PRICE` - Use -1 to clear
- `EMSX_GTD_DATE` - Use -1 to reset to DAY

> **Full Example:** See [ModifyOrderEx](EMSX-API-Complete-Guide.md#modifyorderex) in the Complete Guide for modification patterns and validation rules.

#### CancelOrderEx
Cancels order AND all child routes permanently.

```python
request = service.createRequest("CancelOrderEx")
request.getElement("EMSX_SEQUENCE").appendValue(4733955)
```

> **Full Example:** See [CancelOrderEx](EMSX-API-Complete-Guide.md#cancelorderex) in the Complete Guide for batch cancellation and response handling.

#### DeleteOrder
Deletes order from blotter (different from cancel).

### 4.2 Route Management

#### RouteEx
Creates child route from existing order.

```python
request = service.createRequest("RouteEx")
request.set("EMSX_SEQUENCE", 4116181)  # Parent order
request.set("EMSX_AMOUNT", 100)
request.set("EMSX_BROKER", "BMTB")
request.set("EMSX_ORDER_TYPE", "MKT")
request.set("EMSX_TIF", "DAY")
request.set("EMSX_HAND_INSTRUCTION", "ANY")
request.set("EMSX_TICKER", "IBM US Equity")
# Strategy params available - see full examples
```

> **Full Example:** See [RouteEx](EMSX-API-Complete-Guide.md#routeex) in the Complete Guide for strategy parameters, broker-specific options, and multi-leg routing.

#### ModifyRouteEx
Modifies existing route.

```python
request = service.createRequest("ModifyRouteEx")
request.set("EMSX_SEQUENCE", 4116143)
request.set("EMSX_ROUTE_ID", 2)
request.set("EMSX_AMOUNT", 100)
```

> **Full Example:** See [ModifyRouteEx](EMSX-API-Complete-Guide.md#modifyrouteex) in the Complete Guide for modification constraints and broker handling.

#### CancelRouteEx
Cancels a route (returns order to ASSIGN state if no fills).

```python
request = service.createRequest("CancelRouteEx")
routes = request.getElement("ID_TYPE").setChoice("OrderRoute")
route = routes.appendElement()
route.setElement("EMSX_ROUTE_ID", 1)
route.setElement("EMSX_SEQUENCE", 1234567)
```

> **Full Example:** See [CancelRouteEx](EMSX-API-Complete-Guide.md#cancelrouteex) in the Complete Guide for cancellation workflows and error scenarios.

### 4.3 Basket Operations

#### CreateBasket
Groups orders into a basket.

```python
request = service.createRequest("CreateBasket")
request.set("EMSX_BASKET_NAME", "TestBasket")
request.append("EMSX_SEQUENCE", 4313227)
request.append("EMSX_SEQUENCE", 4313228)
```

> **Full Example:** See [CreateBasket](EMSX-API-Complete-Guide.md#createbasket) in the Complete Guide for basket management and naming conventions.

#### GroupRouteEx
Routes entire basket to broker strategy.

```python
request = service.createRequest("GroupRouteEx")
request.append("EMSX_SEQUENCE", 4116143)
request.append("EMSX_SEQUENCE", 4116144)
request.set("EMSX_AMOUNT_PERCENT", 50)  # % of each order
request.set("EMSX_BROKER", "BB")
request.set("EMSX_ORDER_TYPE", "MKT")
request.set("EMSX_TIF", "DAY")
# Strategy params via EMSX_STRATEGY_PARAMS element
```

> **Full Example:** See [GroupRouteEx](EMSX-API-Complete-Guide.md#grouprouteex) in the Complete Guide for complex basket routing strategies.

### 4.4 Broker & Strategy Info

| Request | Purpose | Complete Guide |
|---------|---------|----------------|
| `GetBrokersWithAssetClass` | List enabled brokers for asset class | [Details](EMSX-API-Complete-Guide.md#getbrokerswithassetclass) |
| `GetBrokerStrategiesWithAssetClass` | List strategies for broker | [Details](EMSX-API-Complete-Guide.md#getbrokerstrategieswithassetclass) |
| `GetBrokerStrategyInfoWithAssetClass` | Get strategy parameter details | [Details](EMSX-API-Complete-Guide.md#getbrokerstrategyinfowithassetclass) |
| `GetAssetClass` | Get asset class from ticker | [Details](EMSX-API-Complete-Guide.md#getassetclass) |

### 4.5 Administrative

| Request | Purpose | Complete Guide |
|---------|---------|----------------|
| `GetAllFieldMetaData` | All field definitions | [Details](EMSX-API-Complete-Guide.md#getallfieldmetadata) |
| `GetFieldMetaData` | Specific field definitions | [Details](EMSX-API-Complete-Guide.md#getfieldmetadata) |
| `GetTeams` | List user's teams | [Details](EMSX-API-Complete-Guide.md#getteams) |
| `GetTradeDesks` | AIM: List trading desks | [Details](EMSX-API-Complete-Guide.md#gettradedesks) |
| `GetTraders` | AIM: List traders | [Details](EMSX-API-Complete-Guide.md#gettraders) |
| `AssignTrader` | Reassign order to different trader | [Details](EMSX-API-Complete-Guide.md#assigntrader) |

---

## 5. Field Reference

> **Complete Field Documentation:** See [Reference - Elements](EMSX-API-Complete-Guide.md#reference---elements) in the Complete Guide for all 200+ field definitions, data types, and valid values.

### 5.1 Essential Fields

| Field | Type | Description |
|-------|------|-------------|
| `EMSX_SEQUENCE` | INT32 | Unique order identifier |
| `EMSX_ROUTE_ID` | INT32 | Route identifier (unique within order) |
| `EMSX_STATUS` | STRING | Order/route status |
| `EVENT_STATUS` | INT32 | Event type (1=heartbeat, 4=initial paint, 6=new, 7=update, 8=delete) |
| `API_SEQ_NUM` | INT64 | Event sequence number |
| `MSG_TYPE` | STRING | Always "E" for EMSX |
| `MSG_SUB_TYPE` | STRING | "O"=Order, "R"=Route |

### 5.2 Order Fields

| Field | Type | Description |
|-------|------|-------------|
| `EMSX_TICKER` | STRING | Security symbol (e.g., "IBM US Equity") |
| `EMSX_AMOUNT` | INT32 | Total order quantity |
| `EMSX_FILLED` | INT32 | Filled quantity |
| `EMSX_WORKING` | INT32 | Working quantity |
| `EMSX_SIDE` | STRING | BUY, SELL, SELL_SHORT |
| `EMSX_ORDER_TYPE` | STRING | MKT, LMT, STP, STP_LMT |
| `EMSX_TIF` | STRING | DAY, GTC, GTD, etc. |
| `EMSX_LIMIT_PRICE` | FLOAT64 | Limit price |
| `EMSX_STOP_PRICE` | FLOAT64 | Stop price |
| `EMSX_BROKER` | STRING | Broker code |
| `EMSX_ACCOUNT` | STRING | Account code |
| `EMSX_BASKET_NAME` | STRING | Basket identifier |
| `EMSX_AVG_PRICE` | FLOAT64 | Average fill price |
| `EMSX_TRADER` | STRING | Trader name |

> **All Order Fields:** See [Order Fields](EMSX-API-Complete-Guide.md#order-fields) in the Complete Guide for complete list including conditional fields and AIM-specific fields.

### 5.3 Route Fields

| Field | Type | Description |
|-------|------|-------------|
| `EMSX_BROKER` | STRING | Route broker |
| `EMSX_BROKER_STATUS` | STRING | Broker status (CXRPRJ, CXLREJ, MODIFIED) |
| `EMSX_AMOUNT` | INT32 | Route quantity |
| `EMSX_FILLED` | INT32 | Filled quantity |
| `EMSX_AVG_PRICE` | FLOAT64 | Average fill price |
| `EMSX_LAST_PRICE` | FLOAT64 | Last fill price |
| `EMSX_LAST_SHARES` | INT32 | Last fill quantity |
| `EMSX_LAST_MARKET` | STRING | Execution venue |

> **All Route Fields:** See [Route Fields](EMSX-API-Complete-Guide.md#route-fields) in the Complete Guide for complete list including execution details.

### 5.4 Special Fields

**Multi-Leg Options:**
- `EMSX_ML_ID` - Multi-leg identifier
- `EMSX_ML_NUM_LEGS` - Number of legs
- `EMSX_ML_RATIO` - Leg ratio
- `EMSX_ML_STRATEGY` - Strategy name

> **Multi-Leg Details:** See [Multi-Leg Fields](EMSX-API-Complete-Guide.md#multi-leg-fields) in the Complete Guide for options trading implementation.

**MiFID II Fields:**
- `EMSX_BROKER_LEI` - Broker LEI
- `EMSX_BUYSIDE_LEI` - Buyside LEI
- `EMSX_SI` - Systematic Internalizer
- `EMSX_GPI` - Global Personal Identifier
- `EMSX_CLIENT_IDENTIFICATION` - Client ID

> **MiFID II Details:** See [MiFID II Compliance](EMSX-API-Complete-Guide.md#mifid-ii-compliance) in the Complete Guide for regulatory field requirements.

---

## 6. Trading API Server

### 6.1 Server vs Desktop API

| Feature | Desktop API (DAPI) | Trading API Server |
|---------|-------------------|-------------------|
| Requires Terminal | Yes | No |
| User Identity | Implied from terminal | Explicit creation |
| Infrastructure | Local | Bloomberg Enterprise |
| Failover | Single point | Paired instances |
| Developer Access | Terminal users only | Any developer |

> **Full Comparison:** See [Trading API Server](EMSX-API-Complete-Guide.md#trading-api-server) in the Complete Guide for deployment architecture and failover configuration.

### 6.2 User Identity Management

Server applications must create user identities:

```python
# 1. Open auth service
session.openService("//blp/apiauth")
authService = session.getService("//blp/apiauth")

# 2. Create identity
identity = session.createIdentity()

# 3. Send auth request
authReq = authService.createAuthorizationRequest()
authReq.set("emrsId", user_uuid)
authReq.set("ipAddress", client_ip)
session.sendAuthorizationRequest(authReq, identity)

# 4. Use identity with requests
session.sendRequest(request, identity, correlationId)
session.subscribe(subscriptions, identity)
```

> **Full Implementation:** See [User Identity Management](EMSX-API-Complete-Guide.md#user-identity-management) in the Complete Guide for UUID management and IP authentication.

---

## 7. Frequently Asked Questions

**Q: What broker should I use for testing?**
A: Use BMTB, BB, EFIX, or API for UAT testing. Contact EMSX Help Desk for production broker enablement.

**Q: Why can't I see my orders?**
A: Most common cause: connected to BETA on API but PROD on terminal (or vice versa). Use UAT ON<GO> to switch terminal to UAT.

**Q: How do I reset a limit price to 0?**
A: Set `EMSX_LIMIT_PRICE` to -99999 when modifying FROM limit TO another order type.

**Q: How do I reset stop price?**
A: Set `EMSX_STOP_PRICE` to -1.

**Q: How do I change GTD to DAY?**
A: Set `EMSX_GTD_DATE` to -1.

**Q: Why are static fields blank?**
A: Static fields (ticker, side, etc.) are only sent on Initial Paint and New events, not Update events.

**Q: How do I track fills?**
A: Use route subscription - each fill generates an UPDATE event. For historical fills, use EMSX History service (max 30 days).

**Q: When is EMSX API unavailable?**
A: Saturdays 1-5pm ET (maintenance). Sunday 9am-1pm ET (router turnaround).

> **Extended FAQ:** See [F.A.Q.](EMSX-API-Complete-Guide.md#faq) in the Complete Guide for additional troubleshooting and edge cases.

---

## 8. Index

### A
- API_SEQ_NUM: [3.1](#31-subscription-basics), [5.1](#51-essential-fields)
- AssignTrader: [4.5](#45-administrative) | [Complete Guide](EMSX-API-Complete-Guide.md#assigntrader)

### B
- Basket: [4.3](#43-basket-operations) | [Complete Guide](EMSX-API-Complete-Guide.md#createbasket)
- Broker codes: [7](#7-frequently-asked-questions)

### C
- CancelOrderEx: [4.1](#41-order-management) | [Complete Guide](EMSX-API-Complete-Guide.md#cancelorderex)
- CancelRouteEx: [4.2](#42-route-management) | [Complete Guide](EMSX-API-Complete-Guide.md#cancelrouteex)
- Connection: [1.2](#12-environment-setup) | [Complete Guide](EMSX-API-Complete-Guide.md#establishing-the-connection)
- Correlation ID: [2.4](#24-correlation-ids)
- CreateBasket: [4.3](#43-basket-operations) | [Complete Guide](EMSX-API-Complete-Guide.md#createbasket)
- CreateOrder: [4.1](#41-order-management) | [Complete Guide](EMSX-API-Complete-Guide.md#createorder)
- CreateOrderAndRouteEx: [4.2](#42-route-management) | [Complete Guide](EMSX-API-Complete-Guide.md#createorderandrouteex)

### D
- DeleteOrder: [4.1](#41-order-management)
- Desktop API: [6.1](#61-server-vs-desktop-api) | [Complete Guide](EMSX-API-Complete-Guide.md#creating-a-session)

### E
- Elements: [5](#5-field-reference) | [Complete Guide](EMSX-API-Complete-Guide.md#reference---elements)
- Endpoints: [1.3](#13-connection-endpoints) | [Complete Guide](EMSX-API-Complete-Guide.md#opening-the-service)
- Environment: [1.2](#12-environment-setup)
- EVENT_STATUS: [3.2](#32-event-status-codes), [5.1](#51-essential-fields)

### F
- Field metadata: [4.5](#45-administrative) | [Complete Guide](EMSX-API-Complete-Guide.md#getallfieldmetadata)
- Fills: [7](#7-frequently-asked-questions)

### G
- GetAllFieldMetaData: [4.5](#45-administrative) | [Complete Guide](EMSX-API-Complete-Guide.md#getallfieldmetadata)
- GetBrokersWithAssetClass: [4.4](#44-broker--strategy-info) | [Complete Guide](EMSX-API-Complete-Guide.md#getbrokerswithassetclass)
- GroupRouteEx: [4.3](#43-basket-operations) | [Complete Guide](EMSX-API-Complete-Guide.md#grouprouteex)

### I
- Identity: [6.2](#62-user-identity-management) | [Complete Guide](EMSX-API-Complete-Guide.md#user-identity-management)
- Initial Paint: [3.2](#32-event-status-codes)

### M
- ModifyOrderEx: [4.1](#41-order-management) | [Complete Guide](EMSX-API-Complete-Guide.md#modifyorderex)
- ModifyRouteEx: [4.2](#42-route-management) | [Complete Guide](EMSX-API-Complete-Guide.md#modifyrouteex)
- MSG_SUB_TYPE: [5.1](#51-essential-fields)
- MSG_TYPE: [5.1](#51-essential-fields)

### O
- Order status: [3.3](#33-order--route-status)

### R
- Route status: [3.3](#33-order--route-status)
- RouteEx: [4.2](#42-route-management) | [Complete Guide](EMSX-API-Complete-Guide.md#routeex)

### S
- Service: [2.1](#21-session--service-model) | [Complete Guide](EMSX-API-Complete-Guide.md#sessions-and-services)
- Session: [2.1](#21-session--service-model) | [Complete Guide](EMSX-API-Complete-Guide.md#creating-a-session)
- Subscription: [3](#3-working-with-subscriptions) | [Complete Guide](EMSX-API-Complete-Guide.md#using-subscriptions)

### T
- Trading API Server: [6](#6-trading-api-server) | [Complete Guide](EMSX-API-Complete-Guide.md#trading-api-server)

### U
- UAT: [1.2](#12-environment-setup)
- UUID: [6.2](#62-user-identity-management)

---

**Document Information:**
- **Purpose:** Quick reference for rapid EMSX API development
- **Companion Document:** [EMSX-API-Complete-Guide.md](EMSX-API-Complete-Guide.md) - Comprehensive documentation with full examples
- **Optimized for:** Developer productivity and rapid information retrieval
- **Source:** Bloomberg EMSX API Documentation
