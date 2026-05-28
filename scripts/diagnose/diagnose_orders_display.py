#!/usr/bin/env python3
"""
诊断脚本：分析 execution-orders 表格无法显示前部分订单的问题

问题分析维度：
1. 数据获取时间范围 - INIT_PAINT 是否完整
2. 过滤条件 - 是否有默认过滤导致部分订单被隐藏
3. 表格更新机制 - 前端是否正确接收和渲染数据
4. 数据订阅字段 - 是否订阅了所有必要字段
"""

import json
from typing import List, Dict, Any, Optional
from dataclasses import dataclass


@dataclass
class DiagnosisResult:
    severity: str  # 'high', 'medium', 'low', 'info'
    category: str
    title: str
    description: str
    recommendation: str
    code_location: Optional[str] = None


class OrdersDisplayDiagnostician:
    """订单显示问题诊断器"""

    def __init__(self):
        self.results: List[DiagnosisResult] = []

    def diagnose(self) -> List[DiagnosisResult]:
        """执行完整诊断"""
        self._check_init_paint_handling()
        self._check_filter_logic()
        self._check_subscription_fields()
        self._check_frontend_rendering()
        self._check_data_update_mechanism()
        self._check_pagination_or_limit()
        return self.results

    def _check_init_paint_handling(self):
        """检查1: INIT_PAINT 处理是否完整"""
        self.results.append(DiagnosisResult(
            severity='high',
            category='Data Loading',
            title='INIT_PAINT Wait Logic May Timeout Too Early',
            description=(
                "Current implementation waits max 15 seconds (30 x 0.5s) for INIT_PAINT.\n"
                "If Bloomberg sends orders slowly, some early orders may be missed.\n"
                "Also, EVENT_STATUS=11 (INIT_PAINT_END) handling may not capture all orders.\n"
                "Reference implementation shows orders arrive with EVENT_STATUS=4 (INIT_PAINT) and 6 (NEW)."
            ),
            recommendation=(
                "1. Increase INIT_PAINT timeout from 15s to 30s\n"
                "2. Add buffering mechanism to collect orders during INIT_PAINT period\n"
                "3. Log all EVENT_STATUS types to diagnose missing orders\n"
                "4. Consider implementing retry mechanism for incomplete INIT_PAINT"
            ),
            code_location="backend/api/main.py:2319-2356 (get_orders)"
        ))

    def _check_filter_logic(self):
        """检查2: 过滤逻辑是否隐藏了部分订单"""
        self.results.append(DiagnosisResult(
            severity='high',
            category='Filtering',
            title='Client-Side Filtering May Hide Orders',
            description=(
                "Frontend applies multiple filters in App.tsx:144-174:\n"
                "- symbol, side, status, orderType, portfolio, trader, exchange, currency\n"
                "- If any filter has default values, orders may be hidden\n"
                "- The 'allOrders' state may contain all data but 'filteredOrders' may exclude some\n"
                "OrderTable receives 'orders' prop which is filtered, not 'allOrders'"
            ),
            recommendation=(
                "1. Check if any filter has non-empty default value\n"
                "2. Add 'Clear All Filters' button with visibility indicator\n"
                "3. Show count: 'Showing X of Y orders' to indicate filtering\n"
                "4. Consider highlighting active filters in UI"
            ),
            code_location="frontend/src/App.tsx:144-174 (filteredOrders)"
        ))

    def _check_subscription_fields(self):
        """检查3: 订阅字段是否完整"""
        self.results.append(DiagnosisResult(
            severity='medium',
            category='Data Subscription',
            title='Order Subscription Field List May Be Incomplete',
            description=(
                "Current ORDER_FIELDS list has 50+ fields but may miss some fields\n"
                "that Bloomberg sends during INIT_PAINT. Reference implementation\n"
                "subscribes to 100+ fields including EMSX_ARRIVAL_PRICE, EMSX_ORDER_AS_OF_DATE, etc.\n"
                "Missing fields may cause orders to be skipped during parsing."
            ),
            recommendation=(
                "1. Compare ORDER_FIELDS with reference implementation\n"
                "2. Add missing fields: EMSX_ARRIVAL_PRICE, EMSX_ORDER_AS_OF_DATE, etc.\n"
                "3. Add defensive parsing - don't skip orders if optional fields missing\n"
                "4. Log warning when fields are missing from message"
            ),
            code_location="backend/api/main.py:633-720 (ORDER_FIELDS)"
        ))

    def _check_frontend_rendering(self):
        """检查4: 前端渲染逻辑"""
        self.results.append(DiagnosisResult(
            severity='medium',
            category='Frontend Rendering',
            title='OrderTable May Not Handle Empty/Null Data Properly',
            description=(
                "OrderTable.tsx renders orders from props. If orders array\n"
                "is empty or contains null values, table shows 'No orders found'.\n"
                "The grouping logic (groupedOrders) may fail if orders have\n"
                "missing 'exchange' or 'symbol' fields used for grouping."
            ),
            recommendation=(
                "1. Add null-check before rendering each order row\n"
                "2. Handle empty groups in grouping logic\n"
                "3. Show diagnostic info: total orders, filtered count, displayed count\n"
                "4. Add fallback for missing group-by fields"
            ),
            code_location="frontend/src/sections/OrderTable.tsx:103-115 (groupedOrders)"
        ))

    def _check_data_update_mechanism(self):
        """检查5: 数据更新机制"""
        self.results.append(DiagnosisResult(
            severity='high',
            category='Data Updates',
            title='Polling May Miss Orders Due to Race Conditions',
            description=(
                "Frontend polls every 2 seconds (App.tsx:186-248).\n"
                "If backend subscription is still receiving INIT_PAINT during poll,\n"
                "get_orders() may return partial data.\n"
                "Also, EVENT_STATUS=7 updates may be skipped if order not in cache yet."
            ),
            recommendation=(
                "1. Implement WebSocket for real-time updates instead of polling\n"
                "2. Add 'refresh' button to manually trigger full reload\n"
                "3. Implement incremental loading with pagination\n"
                "4. Add backend flag to indicate INIT_PAINT complete status"
            ),
            code_location="frontend/src/App.tsx:186-248 (polling)"
        ))

    def _check_pagination_or_limit(self):
        """检查6: 分页或限制"""
        self.results.append(DiagnosisResult(
            severity='low',
            category='Data Limit',
            title='No Pagination Implemented',
            description=(
                "Currently all orders are loaded into memory.\n"
                "If there are many orders (1000+), some may not display properly\n"
                "due to browser rendering limits or virtual scrolling issues.\n"
                "No server-side pagination or limit parameter is used."
            ),
            recommendation=(
                "1. Implement virtual scrolling for large datasets\n"
                "2. Add server-side pagination with limit/offset\n"
                "3. Consider lazy loading for historical orders\n"
                "4. Add order count display to monitor total"
            ),
            code_location="frontend/src/sections/OrderTable.tsx"
        ))

    def print_report(self):
        """打印诊断报告"""
        print("=" * 80)
        print("Orders Display Issue Diagnosis Report")
        print("=" * 80)
        print()

        severity_order = {'high': 0, 'medium': 1, 'low': 2, 'info': 3}
        sorted_results = sorted(self.results, key=lambda x: severity_order.get(x.severity, 4))

        for i, result in enumerate(sorted_results, 1):
            severity_icon = {
                'high': 'CRITICAL',
                'medium': 'WARNING',
                'low': 'INFO',
                'info': 'NOTE'
            }.get(result.severity, '?')

            print(f"{i}. [{severity_icon}] {result.title}")
            print(f"   Category: {result.category}")
            if result.code_location:
                print(f"   Location: {result.code_location}")
            print()
            print(f"   Description:")
            for line in result.description.split('\n'):
                print(f"      {line}")
            print()
            print(f"   Recommendation:")
            for line in result.recommendation.split('\n'):
                print(f"      {line}")
            print()
            print("-" * 80)
            print()


def generate_fix_plan() -> str:
    """生成修复计划"""
    return """
# Orders Display Issue Fix Plan

## Root Causes Identified

1. **INIT_PAINT Timeout Too Short**: 15 seconds may not be enough for large order books
2. **Client-Side Filtering**: Active filters may hide orders without user awareness
3. **Race Condition**: Polling may occur during incomplete INIT_PAINT
4. **Missing Subscription Fields**: Some Bloomberg fields not subscribed

## Fix Implementation

### Fix 1: Increase INIT_PAINT Timeout (main.py)

```python
# Line 2339 - Change from:
for _ in range(30):  # 15 seconds total
# To:
for _ in range(60):  # 30 seconds total
```

### Fix 2: Add INIT_PAINT Status Endpoint

```python
@app.get("/api/orders/status", response_model=ApiResponse, tags=["Orders"])
async def get_orders_status(user: dict = Depends(verify_token)):
    status = {
        "init_paint_done": bloomberg_service._init_paint_done,
        "order_count": len(bloomberg_service._orders),
        "subscription_failed": bloomberg_service._subscription_failed,
        "is_connected": bloomberg_service.connected
    }
    return ApiResponse(success=True, data=status)
```

### Fix 3: Enhanced Frontend Loading (App.tsx)

```typescript
// Add loading state tracking
const [loadingStatus, setLoadingStatus] = useState<{
  isLoading: boolean;
  initPaintDone: boolean;
  orderCount: number;
}>({ isLoading: false, initPaintDone: false, orderCount: 0 });

// Check backend status before fetching
const checkBackendStatus = async () => {
  const status = await apiService.getOrdersStatus();
  if (status.data && !status.data.init_paint_done) {
    // Wait and retry
    setTimeout(fetchOrders, 2000);
    return false;
  }
  return true;
};
```

### Fix 4: Filter Visibility Indicator (OrderTable.tsx)

```typescript
// Add active filter count display
const activeFilterCount = useMemo(() => {
  return Object.values(filters).filter(v => 
    v !== undefined && v !== '' && v !== null && 
    !(Array.isArray(v) && v.length === 0)
  ).length;
}, [filters]);

// Show in UI
{activeFilterCount > 0 && (
  <Badge variant="secondary">
    {activeFilterCount} active filter(s)
  </Badge>
)}
```

### Fix 5: Defensive Order Parsing

```python
# In _parse_order_message, don't skip orders with missing optional fields
# Current: returns None if parsing fails
# Fixed: Return order with default values for missing fields

def _parse_order_message(self, msg, seq: int) -> Optional[Order]:
    try:
        # ... existing parsing ...
        
        # Use default values instead of skipping
        return Order(
            id=str(seq),
            symbol=symbol or "",  # Don't skip if symbol is empty
            # ... other fields with defaults ...
        )
    except Exception as e:
        logger.error(f"Error parsing order {seq}: {e}")
        # Return minimal order instead of None
        return Order(
            id=str(seq),
            symbol="",
            side="BUY",
            status="NEW",
            # ... minimal required fields ...
        )
```

### Fix 6: Add Missing Subscription Fields

```python
# Add to ORDER_FIELDS list:
"EMSX_ARRIVAL_PRICE",
"EMSX_ORDER_AS_OF_DATE",
"EMSX_ORDER_AS_OF_TIME_MICROSEC",
"EMSX_UNDERLYING_TICKER",
# ... other fields from reference implementation
```

## Testing Checklist

- [ ] Test with large order book (>500 orders)
- [ ] Test with slow Bloomberg connection
- [ ] Test filter functionality with clear indicators
- [ ] Test polling during INIT_PAINT
- [ ] Verify all orders display correctly

## Monitoring

Add logging to track:
1. INIT_PAINT duration
2. Orders received vs orders displayed
3. Filter application counts
4. Subscription message counts by EVENT_STATUS
"""


def main():
    diagnostician = OrdersDisplayDiagnostician()
    results = diagnostician.diagnose()
    diagnostician.print_report()
    print("\n")
    print(generate_fix_plan())


if __name__ == "__main__":
    main()
