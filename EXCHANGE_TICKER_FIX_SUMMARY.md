# Exchange/Ticker 字段问题修复总结

## 问题描述
前端在处理部分订单时无法读取 Exchange 和 ticker 字段值。

## 根本原因分析

### 1. 后端 Route 模型缺少字段
- Route 模型原本没有 `ticker` 和 `exchange` 字段
- 这些字段通过 `get_routes()` 方法从父订单动态富化
- 当父订单不在缓存中时，字段值为空字符串

### 2. 数据时序问题
- 路由数据可能通过独立订阅先于父订单到达
- EVENT_STATUS=7 的更新消息只包含动态字段，静态字段（如 EMSX_TICKER）为空
- 如果缓存中没有静态字段，数据会永久丢失

### 3. 空值处理不一致
- Order 模型的 `exchange` 字段为 `Optional[str]` 类型，默认 None
- 富化逻辑中需要额外处理 None 值

## 修复方案

### 后端修复 (main.py)

#### 1. 修改 Order 模型的 exchange 字段类型
```python
# 修改前
exchange: Optional[str] = None

# 修改后  
exchange: str = ""  # 确保始终返回字符串类型
```

#### 2. 在 Route 模型中添加富化字段
```python
# 新增字段到 Route 模型
class Route(BaseModel):
    # ... 原有字段 ...
    
    # Enriched fields from parent order (stored here for persistence)
    ticker: str = ""      # Parent order's symbol (EMSX_TICKER)
    side: str = ""        # Parent order's side
    portfolio: str = ""   # Parent order's portfolio
    trader: str = ""      # Parent order's trader
    traderUuid: int = 0   # Parent order's trader UUID
    currency: str = ""    # Parent order's currency
    exchange: str = ""    # Parent order's exchange (EMSX_EXCHANGE)
```

#### 3. 增强路由富化逻辑
- 优先使用路由自身的缓存值（如果已存在）
- 其次从父订单获取
- 添加详细的日志记录
- 当父订单不存在时，保留路由的缓存值

#### 4. 改进路由更新合并逻辑
- 在 EVENT_STATUS=7 更新时，始终保留富化字段（ticker, side, portfolio, trader, traderUuid, currency, exchange）
- 防止更新消息中的空值覆盖已缓存的富化数据

#### 5. 实现延迟富化机制
- 当新订单（EVENT_STATUS=4 或 6）到达时，自动查找并富化相关的路由
- 解决路由先于父订单到达的问题

### 前端修复

#### 1. RouteTable.tsx
- Ticker 显示：`route.ticker || '-'`
- Exchange 显示：`route.exchange || '-'`
- Ticker 过滤：`(r.ticker || '').toUpperCase().includes(t)`

#### 2. route-modify-dialogs.tsx
- Ticker 显示：`route.ticker || '-'`

## 修改的文件列表

### 后端
- `Execution/backend/api/main.py`
  - Order.exchange 字段类型修改 (行 242)
  - Route 模型添加富化字段 (行 375-382)
  - get_routes() 富化逻辑增强 (行 2485-2520)
  - _process_order_message 添加延迟富化调用 (行 1263)
  - _enrich_routes_with_new_order 新方法 (行 1267-1290)
  - _process_route_message 合并逻辑增强 (行 1310-1320)

### 前端
- `Execution/frontend/src/sections/RouteTable.tsx`
  - Ticker 显示默认值 (行 456)
  - Exchange 显示默认值 (行 458)
  - Ticker 过滤空值处理 (行 135)

- `Execution/frontend/src/components/route-modify-dialogs.tsx`
  - Ticker 显示默认值 (行 80)

## 验证建议

### 1. 单元测试
- 测试路由富化逻辑，包括父订单存在和不存在的情况
- 测试 EVENT_STATUS=7 更新时富化字段的保留
- 测试延迟富化机制

### 2. 集成测试
- 模拟路由先于父订单到达的场景
- 验证前端正确显示默认值
- 验证过滤功能正常工作

### 3. 日志监控
- 监控 `Enrich route` 日志，确保富化成功
- 监控 `Delayed enrichment` 日志，确认延迟富化触发
- 监控 `no parent order found` 警告，分析缺失原因

## 回滚方案

如需回滚，请恢复以下更改：

1. 恢复 Order.exchange 字段类型为 `Optional[str] = None`
2. 从 Route 模型中移除富化字段
3. 恢复原始的 get_routes() 富化逻辑
4. 恢复原始的 _process_route_message 合并逻辑
5. 移除 _enrich_routes_with_new_order 方法
6. 恢复前端默认值为原始值

## 相关代码位置

### 关键日志输出
- `Enrich route {id}: parent seq={seq}, route.ticker='{old}'->'{new}'`
- `Delayed enrichment for route {key}: ticker='{ticker}', exchange='{exchange}'`
- `Enriched {count} routes for new order {seq}`
- `Enrich route {id}: no parent order found for seq={seq} and no cached values`
