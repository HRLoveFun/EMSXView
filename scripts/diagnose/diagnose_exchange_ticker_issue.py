#!/usr/bin/env python3
"""
诊断脚本：排查前端无法读取 Exchange 和 Ticker 字段的问题

问题描述：
前端在处理部分订单时无法读取 Exchange 和 ticker 字段值

该脚本分析：
1. 后端API返回数据是否完整
2. 数据映射逻辑是否正确
3. 默认值处理和数据格式是否存在异常
"""

import json
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DiagnosisResult:
    """诊断结果"""
    severity: str  # 'high', 'medium', 'low', 'info'
    category: str
    title: str
    description: str
    recommendation: str
    code_location: Optional[str] = None


class ExchangeTickerDiagnostician:
    """
    Exchange 和 Ticker 字段问题诊断器
    """

    def __init__(self):
        self.results: List[DiagnosisResult] = []

    def diagnose(self) -> List[DiagnosisResult]:
        """执行完整诊断"""
        self._check_backend_route_model()
        self._check_route_enrichment_logic()
        self._check_event_status_handling()
        self._check_frontend_type_definition()
        self._check_data_flow_timing()
        self._check_null_handling()
        return self.results

    def _check_backend_route_model(self):
        """检查1: 后端 Route 模型是否包含 ticker/exchange 字段"""
        self.results.append(DiagnosisResult(
            severity='high',
            category='Data Model',
            title='Route Model Missing ticker and exchange Fields',
            description=(
                "Backend Route model (main.py:292-375) does not define ticker and exchange fields.\n"
                "These fields are dynamically enriched from parent order in get_routes() method.\n"
                "When parent order cache does not exist, these fields are set to empty strings."
            ),
            recommendation=(
                "1. Add optional ticker and exchange fields to Route model\n"
                "2. Or ensure valid parent order data in enrichment logic"
            ),
            code_location="Execution/backend/api/main.py:292-375 (Route model)"
        ))

    def _check_route_enrichment_logic(self):
        """检查2: 路由富化逻辑"""
        self.results.append(DiagnosisResult(
            severity='high',
            category='Data Mapping',
            title='Route Enrichment Depends on Parent Order Cache',
            description=(
                "In get_routes() method (main.py:2476-2501):\n"
                "- Route's ticker and exchange fields come from parent's symbol and exchange fields\n"
                "- If parent is None (order not in cache), fields are set to empty strings\n"
                "- No handling for case where parent exists but exchange is None"
            ),
            recommendation=(
                "1. Add more logging to confirm why parent lookup fails\n"
                "2. If parent doesn't exist, try delayed enrichment or get data from other sources\n"
                "3. Ensure exchange field handles None correctly, use empty string as default"
            ),
            code_location="Execution/backend/api/main.py:2476-2501 (get_routes enrichment)"
        ))

    def _check_event_status_handling(self):
        """检查3: 事件状态处理"""
        self.results.append(DiagnosisResult(
            severity='medium',
            category='Data Update',
            title='EVENT_STATUS=7 Updates May Cause Data Loss',
            description=(
                "In _process_order_message (main.py:1193-1242):\n"
                "- EVENT_STATUS=7 (update) only contains dynamic fields\n"
                "- Static fields (EMSX_TICKER, EMSX_SIDE, EMSX_EXCHANGE etc.) will be empty\n"
                "- System merges with cached data to preserve static fields\n"
                "- But if cache also lacks these fields, data is permanently lost"
            ),
            recommendation=(
                "1. Ensure INIT_PAINT (EVENT_STATUS=4) or new order (EVENT_STATUS=6) arrives before updates\n"
                "2. In merge logic, check if key fields are empty, preserve cache value if so\n"
                "3. Add warning log when key static fields are empty in update message"
            ),
            code_location="Execution/backend/api/main.py:1193-1242 (_process_order_message)"
        ))

    def _check_frontend_type_definition(self):
        """检查4: 前端类型定义"""
        self.results.append(DiagnosisResult(
            severity='low',
            category='Type Definition',
            title='Frontend Route Type Requires ticker and exchange as Required Strings',
            description=(
                "Frontend Route interface (types/index.ts:110-117):\n"
                "- ticker: string (required)\n"
                "- exchange: string (required)\n"
                "- Backend returning empty strings can be handled by frontend\n"
                "- But null/undefined may cause issues"
            ),
            recommendation=(
                "1. Frontend can add default handling: route.ticker || '(unknown)'\n"
                "2. Or use optional chaining: route.ticker ?? ''"
            ),
            code_location="Execution/frontend/src/types/index.ts:110-117"
        ))

    def _check_data_flow_timing(self):
        """检查5: 数据流时序问题"""
        self.results.append(DiagnosisResult(
            severity='medium',
            category='Timing Issue',
            title='Route Data May Arrive Before Parent Order',
            description=(
                "In _process_route_message (main.py:1294-1328):\n"
                "- Route data is received via independent subscription\n"
                "- If route message arrives before parent order INIT_PAINT, enrichment fails\n"
                "- Route cache stores data without parent order information"
            ),
            recommendation=(
                "1. Mark routes as 'pending_enrichment' when enrichment fails\n"
                "2. When new order is added to cache, re-trigger enrichment for related routes\n"
                "3. Or implement a periodic task to retry failed enrichments"
            ),
            code_location="Execution/backend/api/main.py:1294-1328 (_process_route_message)"
        ))

    def _check_null_handling(self):
        """检查6: 空值处理"""
        self.results.append(DiagnosisResult(
            severity='medium',
            category='Null Handling',
            title='Exchange Field Null Handling Inconsistent',
            description=(
                "In _parse_order_message (main.py:1625):\n"
                "- exchange = self._msg_safe_str(msg, 'EMSX_EXCHANGE') or None\n"
                "- This returns None if EMSX_EXCHANGE is empty\n"
                "- But in enrichment logic: parent.exchange if parent.exchange else ''\n"
                "- OrderTable.tsx displays: order.exchange || ''"
            ),
            recommendation=(
                "1. Unify null handling: always use empty string instead of None\n"
                "2. In Order model, set exchange default to '' instead of None\n"
                "3. Provide default value when _msg_safe_str returns empty string"
            ),
            code_location="Execution/backend/api/main.py:1625, 1208"
        ))

    def print_report(self):
        """打印诊断报告"""
        print("=" * 80)
        print("Exchange/Ticker Field Issue Diagnosis Report")
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
    """生成修复计划文档"""
    return """
# Exchange/Ticker Field Issue Fix Plan

## Root Causes

1. **Data Model Inconsistency**: Backend Route model lacks ticker and exchange fields, 
   these fields are dynamically enriched from parent order
2. **Cache Dependency**: When parent order is not in cache, fields are empty strings
3. **Timing Issue**: Route data may arrive before parent order

## Fix Approaches

### Approach A: Backend Enhancement (Recommended)

1. **Modify Order Model** (main.py:242)
   - Change exchange field default from None to empty string
   - Ensure always returns string type

2. **Enhance Route Enrichment Logic** (main.py:2476-2501)
   - Add logging for parent order lookup failures
   - Implement delayed enrichment mechanism
   - Re-enrich routes when parent order arrives

3. **Improve Update Merge Logic** (main.py:1193-1242)
   - Ensure static fields are not overwritten during merge
   - Add more defensive checks

### Approach B: Frontend Enhancement

1. **Add Default Handling**
   - RouteTable.tsx: Change route.ticker to route.ticker || '(unknown)'
   - OrderTable.tsx: Already has order.exchange || ''

2. **Add Type Guards**
   - Check data existence before displaying

## Suggested Code Changes

### Change 1: Order Model exchange Field Default

```python
# main.py:242
exchange: Optional[str] = None  # Change to:
exchange: str = ""  # Ensure always returns string
```

### Change 2: Enhanced Route Enrichment Logic

```python
# main.py:2476-2501 area
async def get_routes(self) -> List[dict]:
    # ... existing code ...
    
    enriched = []
    for r in routes:
        r_dict = r.model_dump()
        parent = orders_snapshot.get(str(r.sequence))
        if parent:
            r_dict["ticker"] = parent.symbol or ""
            r_dict["exchange"] = parent.exchange or ""
            # ... other fields ...
        else:
            # Log and mark for delayed enrichment
            logger.warning(f"Route {r.id}: Parent order seq={r.sequence} not found")
            r_dict["ticker"] = ""
            r_dict["exchange"] = ""
            r_dict["_pending_enrichment"] = True
        enriched.append(r_dict)
    return enriched
```

### Change 3: Implement Delayed Enrichment

```python
# In _process_order_message, when new order is added to cache:
def _process_order_message(self, msg):
    # ... existing code ...
    
    # NEW: When new order added, try to enrich related routes
    if event_status in (4, 6):  # INIT_PAINT or new order
        self._enrich_routes_for_order(seq_key)

def _enrich_routes_for_order(self, order_seq: str):
    # When order arrives, re-enrich related routes
    with self._data_lock:
        order = self._orders.get(order_seq)
        if not order:
            return
        
        for route_key, route in self._routes.items():
            if str(route.sequence) == order_seq:
                # Update route enrichment fields
                if not route.ticker:  # If needs delayed enrichment
                    logger.info(f"Delayed enrichment for route {route_key} using order {order_seq}")
```

## Testing

1. Test Case 1: Route request when parent order cache does not exist
2. Test Case 2: Static field retention during EVENT_STATUS=7 updates
3. Test Case 3: Delayed route enrichment after new order arrival
"""


def main():
    # Run diagnosis
    diagnostician = ExchangeTickerDiagnostician()
    results = diagnostician.diagnose()
    diagnostician.print_report()

    # Generate fix plan
    print("\n")
    print(generate_fix_plan())


if __name__ == "__main__":
    main()
