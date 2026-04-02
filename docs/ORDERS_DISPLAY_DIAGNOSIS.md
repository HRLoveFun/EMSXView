# Execution Orders 表格显示问题 - 诊断与修复报告

## 问题描述
execution-orders 表格无法正常显示前部分订单，部分历史订单缺失。

## 根本原因分析

### 1. INIT_PAINT 超时时间过短 (严重)
**位置:** `Execution/backend/api/main.py:2339`

**问题:**
- 原超时时间为 15 秒 (30 x 0.5s)
- Bloomberg 发送大订单簿时可能超过此时间
- 超时后返回部分数据，导致前端显示不完整

**参考实现对比:**
Bloomberg 官方示例 (EMSXSubscriptions.py) 显示：
- 订单通过 EVENT_STATUS=4 (INIT_PAINT) 和 6 (NEW) 接收
- 大订单簿可能需要 20-30 秒完成传输

### 2. 竞态条件 (严重)
**位置:** `Execution/frontend/src/App.tsx:186-248`

**问题:**
- 前端每 2 秒轮询一次
- 如果轮询发生在 INIT_PAINT 进行中，返回不完整数据
- 没有机制等待 INIT_PAINT 完成后再显示

### 3. 过滤条件不可见 (中等)
**位置:** `Execution/frontend/src/sections/OrderTable.tsx`

**问题:**
- 用户可能无意中应用了过滤条件
- 没有显示当前过滤状态
- 无法直观了解为何部分订单不显示

### 4. 缺少状态查询 API (中等)
**问题:**
- 前端无法查询后端 INIT_PAINT 状态
- 无法判断数据是否完整
- 无法给用户加载进度反馈

## 修复方案

### 修复 1: 增加 INIT_PAINT 超时时间
```python
# 修改前
for _ in range(30):  # 15秒

# 修改后  
for _ in range(60):  # 30秒
    # 额外等待 2 秒确保捕获尾随订单
```

**文件:** `Execution/backend/api/main.py:2339-2351`

### 修复 2: 添加订单状态 API
```python
@app.get("/api/orders/status")
async def get_orders_status():
    return {
        "init_paint_done": bool,
        "order_count": int,
        "route_count": int,
        "subscription_failed": bool,
        "is_connected": bool
    }
```

**文件:** `Execution/backend/api/main.py:3162-3184`

### 修复 3: 前端添加过滤指示器
```typescript
// 显示活跃过滤器数量
({activeFilterCount} filters active)

// 显示订单计数
Showing {orders.length} of {allOrders.length} orders

// 调试日志
[OrderTable] allOrders: X, orders: Y, activeFilters: Z
```

**文件:** `Execution/frontend/src/sections/OrderTable.tsx`

### 修复 4: 前端 API 服务方法
```typescript
async getOrdersStatus(): Promise<ApiResponse<{
  init_paint_done: boolean;
  order_count: number;
  route_count: number;
  subscription_failed: boolean;
  is_connected: boolean;
}>>
```

**文件:** `Execution/frontend/src/services/api.ts:151-159`

## 修改文件列表

| 文件 | 修改类型 | 说明 |
|------|----------|------|
| `Execution/backend/api/main.py` | 修改+新增 | 增加超时，添加状态API |
| `Execution/frontend/src/services/api.ts` | 新增 | getOrdersStatus 方法 |
| `Execution/frontend/src/sections/OrderTable.tsx` | 修改 | 过滤指示器，调试日志 |

## 验证测试

运行测试脚本验证所有修复:
```bash
python scripts/test_orders_display_fix.py
```

测试结果:
- [x] INIT_PAINT 超时增加到 30 秒
- [x] 订单状态 API 端点
- [x] 前端 API 服务方法
- [x] 前端过滤指示器
- [x] 尾随订单等待逻辑

## 监控建议

### 关键日志
```
# 后端日志
INIT_PAINT inferred complete — X orders in cache
Orders arriving: X so far, waiting for more...
INIT_PAINT not complete after 30s — returning partial snapshot

# 前端控制台
[OrderTable] allOrders: X, orders: Y, activeFilters: Z
```

### 指标监控
1. INIT_PAINT 完成时间
2. 订单数量变化
3. 过滤器使用率
4. API 响应时间

## 后续优化建议

### 短期
1. 添加 WebSocket 实时更新
2. 实现虚拟滚动处理大订单簿
3. 添加加载进度指示器

### 长期
1. 服务端分页
2. 订单数据缓存策略
3. 增量更新机制

## 参考文档

- Bloomberg EMSX API 官方文档
- `scripts/diagnose/diagnose_orders_display.py` - 诊断脚本
- `ORDERS_DISPLAY_FIX_SUMMARY.md` - 修复总结
- GitHub 参考: HRLoveFun/Bloomberg-EMSX-API-Code-Examples

## 回滚方案

如需回滚，恢复以下更改:
1. 将 `range(60)` 改回 `range(30)`
2. 移除 `/api/orders/status` 端点
3. 移除 OrderTable 中的过滤指示器代码
4. 移除 api.ts 中的 getOrdersStatus 方法
