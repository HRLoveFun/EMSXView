# Route 修改功能实现文档

## 概述
根据 `ROUTE_MODIFY_FEATURES.md` 的规划，已实现 Route Table 的修改功能。

## 实现的功能

### 1. 前端功能

#### 操作菜单 (RouteActionMenu)
- 每行添加操作按钮（三个点图标）
- 下拉菜单包含以下操作：
  - **Cancel Route** - 取消路由
  - **Modify Quantity** - 修改数量
  - **Modify Order Type** - 修改订单类型
  - **Modify Limit Price** - 修改限价
  - **Modify Strategy** - 修改策略
  - **Change Broker** - 更改经纪商

#### 状态控制
- 只有可修改状态的 Route 才显示操作菜单
- 可修改状态：`SENT`, `WORKING`, `PARTFILL`, `QUEUED`, `HOLD`
- 不可修改状态的操作按钮被禁用

#### 弹窗组件

**CancelRouteDialog**
- 确认对话框
- 显示 Route 信息（Sequence, RouteID, Ticker, Status）
- 确认后调用 CancelRouteEx

**ModifyAmountDialog**
- 输入新数量
- 显示当前数量和已成交数量
- 验证：新数量必须 >= 已成交数量

**ModifyOrderTypeDialog**
- 下拉选择：MKT, LMT, STP, STOP_LIMIT
- 选择 LMT 时显示限价输入框
- 选择 STP/STOP_LIMIT 时显示止损价输入框
- TIF 选择：DAY, GTC, IOC, FOK, GTD

**ModifyLimitPriceDialog**
- 修改限价
- 显示当前限价
- 可清空限价

**ModifyStrategyDialog**
- 策略选择：VWAP, TWAP, POV, IS
- 参数设置：开始时间、结束时间、最大成交量百分比

**ChangeBrokerDialog**
- 经纪商选择（下拉或手动输入）
- 交易所目的地输入

### 2. 后端功能

#### 新增数据模型
```python
class CancelRouteRequest(BaseModel):
    sequence: int      # EMSX_SEQUENCE
    routeId: int       # EMSX_ROUTE_ID

class ModifyRouteRequest(BaseModel):
    sequence: int
    routeId: int
    amount: Optional[int]
    orderType: Optional[str]
    limitPrice: Optional[float]
    stopPrice: Optional[float]
    tif: Optional[str]
    broker: Optional[str]
    exchangeDestination: Optional[str]
    notes: Optional[str]
    strategyParams: Optional[Dict[str, Any]]
```

#### 新增 API 端点
```
POST /api/routes/cancel
POST /api/routes/modify
```

#### Bloomberg EMSX 服务方法
```python
async def cancel_route(self, request_data: CancelRouteRequest) -> bool
async def modify_route(self, request_data: ModifyRouteRequest) -> bool
```

### 3. 文件变更

#### 新增文件
- `app/src/components/route-action-menu.tsx` - 操作菜单组件
- `app/src/components/route-modify-dialogs.tsx` - 修改弹窗组件

#### 修改文件
- `app/src/types/index.ts` - 添加 CancelRouteRequest, ModifyRouteRequest 类型
- `app/src/services/api.ts` - 添加 cancelRoute, modifyRoute API 方法
- `app/src/sections/RouteTable.tsx` - 集成操作菜单和弹窗
- `app/src/App.tsx` - 传递 API 处理函数给 RouteTable
- `emsx-backend/backend/main.py` - 添加后端 API 端点和服务方法

## EMSX API 对应关系

| UI 功能 | EMSX API | 关键字段 |
|---------|----------|----------|
| Cancel Route | CancelRouteEx | EMSX_SEQUENCE, EMSX_ROUTE_ID |
| Modify Quantity | ModifyRouteEx | EMSX_AMOUNT |
| Modify Order Type | ModifyRouteEx | EMSX_ORDER_TYPE, EMSX_TIF |
| Modify Limit Price | ModifyRouteEx | EMSX_LIMIT_PRICE |
| Modify Stop Price | ModifyRouteEx | EMSX_STOP_PRICE |
| Change Broker | ModifyRouteEx | EMSX_BROKER, EMSX_EXCHANGE_DESTINATION |
| Modify Strategy | ModifyRouteEx | EMSX_STRATEGY_NAME, EMSX_STRATEGY_FIELDS |

## 使用说明

1. 在 Route Table 中，每行最右侧会显示操作菜单按钮（三个点）
2. 点击按钮展开操作菜单
3. 选择需要的操作
4. 在弹窗中输入新值并确认
5. 系统会发送请求到 Bloomberg EMSX API
6. 操作成功后显示提示并刷新数据

## 注意事项

1. 所有修改操作都需要用户确认
2. 只有特定状态的 Route 可以修改
3. 修改数量时不能小于已成交数量
4. 修改订单类型时可能需要同时设置价格
5. 操作结果依赖 Bloomberg EMSX API 的响应
