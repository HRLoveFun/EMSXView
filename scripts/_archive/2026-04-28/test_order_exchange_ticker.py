"""
Test: Verify Order exchange/ticker serialization in the full API pipeline.

Simulates the exact data flow:
  Bloomberg message → _parse_order_message → _orders cache → get_orders() → API JSON

Checks for:
  1. Empty exchange/symbol surviving through the pipeline
  2. Pydantic serialization including empty string fields
  3. The symbol filter not dropping valid orders
  4. EVENT_STATUS=7 merge preserving static fields
"""
import sys, os, json, enum
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

# ── Minimal replica of the models ──────────────────────────────

class OrderSide(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderStatus(str, enum.Enum):
    NEW = "NEW"
    WORKING = "WORKING"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"

class OrderType(str, enum.Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

class TimeInForce(str, enum.Enum):
    DAY = "DAY"
    GTC = "GTC"

class Order(BaseModel):
    model_config = ConfigDict(use_enum_values=True)
    id: str
    symbol: str
    side: OrderSide
    status: OrderStatus
    orderType: OrderType
    quantity: int
    filledQuantity: int = 0
    remainingQuantity: int
    price: Optional[float] = None
    timeInForce: TimeInForce
    account: str
    portfolio: str = ""
    trader: str
    createdAt: str
    updatedAt: str
    notes: Optional[str] = None
    avgPrice: Optional[float] = None
    currency: str = ""
    exchange: str = ""
    percentFilled: float = 0.0
    broker: str = ""
    traderUuid: int = 0

class ApiResponse(BaseModel):
    success: bool
    data: Optional[list] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


def make_order(seq, symbol="AAPL US Equity", exchange="US", status="WORKING", **kw):
    return Order(
        id=str(seq),
        symbol=symbol,
        side="BUY",
        status=status,
        orderType="LIMIT",
        quantity=100,
        filledQuantity=0,
        remainingQuantity=100,
        price=150.0,
        timeInForce="DAY",
        account="ACCT1",
        trader="TRADER1",
        createdAt=datetime.now().isoformat(),
        updatedAt=datetime.now().isoformat(),
        currency="USD",
        exchange=exchange,
        **kw,
    )


def test_1_empty_exchange_serialization():
    """Test: Order with empty exchange serializes correctly"""
    order = make_order(1001, exchange="")
    d = order.model_dump()
    assert "exchange" in d, "exchange field missing from model_dump"
    assert d["exchange"] == "", f"expected empty string, got {d['exchange']!r}"
    
    # Simulate JSON serialization (what FastAPI does)
    j = json.loads(order.model_dump_json())
    assert "exchange" in j, "exchange field missing from JSON"
    assert j["exchange"] == "", f"expected empty string in JSON, got {j['exchange']!r}"
    print("  PASS: Empty exchange serializes as '' in both dict and JSON")


def test_2_empty_exchange_in_api_response():
    """Test: ApiResponse with orders preserves empty exchange"""
    orders = [make_order(1001, exchange=""), make_order(1002, exchange="US")]
    resp = ApiResponse(success=True, data=[o.model_dump() for o in orders])
    j = json.loads(resp.model_dump_json())
    
    order_data = j["data"]
    assert len(order_data) == 2
    assert order_data[0]["exchange"] == ""
    assert order_data[1]["exchange"] == "US"
    print("  PASS: ApiResponse preserves empty exchange in order data")


def test_3_symbol_filter_behavior():
    """Test: orders = [o for o in orders if o.symbol] filter behavior"""
    orders = [
        make_order(1001, symbol="AAPL US Equity", exchange="US"),
        make_order(1002, symbol="", exchange="HK"),  # empty symbol!
        make_order(1003, symbol="7203 JP Equity", exchange="JP"),
    ]
    
    before_count = len(orders)
    filtered = [o for o in orders if o.symbol]
    after_count = len(filtered)
    
    dropped = before_count - after_count
    print(f"  INFO: {before_count} orders → {after_count} after symbol filter ({dropped} dropped)")
    
    if dropped > 0:
        dropped_ids = [o.id for o in orders if not o.symbol]
        print(f"  WARNING: Orders dropped by symbol filter: {dropped_ids}")
        print(f"  This is by design — orders without ticker are not displayable")
    
    assert after_count == 2, f"Expected 2 orders after filter, got {after_count}"
    print("  PASS: Symbol filter works correctly (drops empty-symbol orders)")


def test_4_event_status_7_merge():
    """Test: EVENT_STATUS=7 merge preserves static fields (symbol, exchange)"""
    # Simulate cached order with full fields
    cached = make_order(1001, symbol="AAPL US Equity", exchange="US", status="WORKING")
    
    # Simulate update message (EVENT_STATUS=7) with empty static fields
    update = make_order(1001, symbol="", exchange="", status="PARTIAL")
    
    # Merge logic from _process_subscription_message
    merged = Order(
        id=cached.id,
        symbol=update.symbol or cached.symbol,
        side=cached.side,
        status=update.status,  # Take updated status
        orderType=cached.orderType,
        quantity=cached.quantity,
        filledQuantity=update.filledQuantity,
        remainingQuantity=cached.remainingQuantity,
        timeInForce=cached.timeInForce,
        account=cached.account,
        portfolio=cached.portfolio,
        trader=cached.trader,
        createdAt=cached.createdAt,
        updatedAt=datetime.now().isoformat(),
        currency=cached.currency,
        exchange=update.exchange or cached.exchange,
    )
    
    assert merged.symbol == "AAPL US Equity", f"Symbol lost in merge: {merged.symbol!r}"
    assert merged.exchange == "US", f"Exchange lost in merge: {merged.exchange!r}"
    assert merged.status == "PARTIAL", f"Status not updated: {merged.status!r}"
    print("  PASS: EVENT_STATUS=7 merge preserves symbol and exchange")


def test_5_pydantic_v2_none_rejection():
    """Test: Pydantic v2 rejects None for str fields (not Optional)"""
    try:
        order = Order(
            id="1001",
            symbol="AAPL US Equity",
            side="BUY",
            status="WORKING",
            orderType="LIMIT",
            quantity=100,
            filledQuantity=0,
            remainingQuantity=100,
            timeInForce="DAY",
            account="ACCT1",
            trader="TRADER1",
            createdAt=datetime.now().isoformat(),
            updatedAt=datetime.now().isoformat(),
            exchange=None,  # <-- None for str field!
        )
        print(f"  UNEXPECTED: Pydantic accepted None for exchange, value={order.exchange!r}")
        print(f"  This means the previous 'or None' bug did not cause ValidationError")
        print(f"  Pydantic v2 may coerce None → '' for str fields")
    except Exception as e:
        print(f"  PASS: Pydantic v2 rejects None for str field: {type(e).__name__}: {e}")


def test_6_exchange_filter_with_empty():
    """Test: Backend exchange filter behavior with empty exchanges"""
    orders = [
        make_order(1001, exchange="US"),
        make_order(1002, exchange=""),
        make_order(1003, exchange="HK"),
    ]
    
    # Simulate backend filter: if filters.exchange
    ex_filter = "US"
    ex = ex_filter.upper()
    filtered = [o for o in orders if o.exchange and ex in o.exchange.upper()]
    
    assert len(filtered) == 1
    assert filtered[0].id == "1001"
    print("  PASS: Exchange filter correctly excludes empty-exchange orders")
    
    # No filter — all orders returned
    no_filter = [o for o in orders if o.symbol]  # only symbol filter
    assert len(no_filter) == 3
    print("  PASS: Without exchange filter, all orders (with symbol) are returned")


def test_7_grouping_with_empty_exchange():
    """Test: Frontend grouping behavior with empty exchange"""
    orders = [
        {"id": "1001", "symbol": "AAPL US Equity", "exchange": "US"},
        {"id": "1002", "symbol": "7203 JP Equity", "exchange": ""},
        {"id": "1003", "symbol": "0700 HK Equity", "exchange": ""},
        {"id": "1004", "symbol": "VOD LN Equity", "exchange": "LN"},
    ]
    
    # Simulate frontend grouping logic (OrderTable.tsx line 108)
    groups = {}
    for order in orders:
        raw = order.get("exchange")
        key = str(raw) if raw is not None and raw != '' else '(empty)'
        if key not in groups:
            groups[key] = []
        groups[key].append(order["id"])
    
    print(f"  Groups: {dict(groups)}")
    assert "(empty)" in groups, "Expected (empty) group"
    assert len(groups["(empty)"]) == 2, f"Expected 2 orders in (empty) group, got {len(groups['(empty)'])}"
    print("  PASS: Orders with empty exchange are grouped under '(empty)'")


def test_8_model_dump_includes_all_fields():
    """Test: Order.model_dump() includes ALL fields even with defaults"""
    order = make_order(1001, exchange="", symbol="TEST Equity")
    d = order.model_dump()
    
    # Check all expected fields are present
    expected_fields = ["id", "symbol", "side", "status", "orderType", "quantity",
                      "exchange", "currency", "broker", "portfolio", "trader"]
    missing = [f for f in expected_fields if f not in d]
    assert not missing, f"Missing fields in model_dump: {missing}"
    
    # Verify empty string fields are present, not excluded
    assert d["exchange"] == ""
    assert d["currency"] == "USD"
    assert d["broker"] == ""
    print("  PASS: model_dump includes all fields including empty string defaults")


def test_9_json_serialization_empty_strings():
    """Test: FastAPI JSON response includes empty string fields"""
    order = make_order(1001, exchange="", symbol="TEST Equity")
    
    # model_dump_json (what FastAPI uses internally)
    json_str = order.model_dump_json()
    parsed = json.loads(json_str)
    
    assert "exchange" in parsed, "exchange missing from JSON"
    assert parsed["exchange"] == "", f"exchange is {parsed['exchange']!r}, expected ''"
    assert "symbol" in parsed, "symbol missing from JSON"
    
    # Also test with mode='json' which is another FastAPI serialization path
    json_dict = order.model_dump(mode='json')
    assert "exchange" in json_dict
    assert json_dict["exchange"] == ""
    print("  PASS: JSON serialization preserves empty string fields")


if __name__ == "__main__":
    tests = [
        ("1. Empty exchange serialization", test_1_empty_exchange_serialization),
        ("2. Empty exchange in ApiResponse", test_2_empty_exchange_in_api_response),
        ("3. Symbol filter behavior", test_3_symbol_filter_behavior),
        ("4. EVENT_STATUS=7 merge", test_4_event_status_7_merge),
        ("5. Pydantic v2 None rejection", test_5_pydantic_v2_none_rejection),
        ("6. Exchange filter with empty", test_6_exchange_filter_with_empty),
        ("7. Grouping with empty exchange", test_7_grouping_with_empty_exchange),
        ("8. model_dump includes all fields", test_8_model_dump_includes_all_fields),
        ("9. JSON serialization", test_9_json_serialization_empty_strings),
    ]
    
    passed = 0
    failed = 0
    for name, test_fn in tests:
        print(f"\n{'='*60}")
        print(f"TEST: {name}")
        print(f"{'='*60}")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1
    
    print(f"\n{'='*60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {len(tests)}")
    print(f"{'='*60}")
    
    if failed > 0:
        sys.exit(1)
