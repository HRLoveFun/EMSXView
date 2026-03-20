# Route Table 修改功能规格说明

## 概述
根据 EMSX API Developer's Guide，在 Route Table 中添加修改 route 的功能。

## EMSX API 支持的路由操作

### 1. CancelRouteEx - 取消路由
**API Endpoint**: `//blp/emapisvc/CancelRouteEx`

**请求参数**:
- `EMSX_SEQUENCE` - 订单序列号 (必填)
- `EMSX_ROUTE_ID` - 路由ID (必填)
- `EMSX_TRADER_UUID` - 交易员UUID (可选，如果与发送请求的UUID不同)
- `EMSX_MANUAL_ORD_INDICATOR` - 手动订单标识 (可选)

**说明**:
- 发送取消请求到执行场所
- 取消后 route 状态变为 CANCEL 或相关状态
- 需要执行场所确认后才能生效

### 2. ModifyRouteEx - 修改路由
**API Endpoint**: `//blp/emapisvc/ModifyRouteEx`

**必填字段**:
- `EMSX_SEQUENCE` - 订单序列号
- `EMSX_ROUTE_ID` - 路由ID
- `EMSX_AMOUNT` - 数量
- `EMSX_ORDER_TYPE` - 订单类型 (MKT, LMT, STP, STOP_LIMIT)
- `EMSX_TIF` - Time In Force (DAY, GTC, IOC, FOK, GTD)

**可选字段**:
- `EMSX_LIMIT_PRICE` - 限价
  - 0 = 忽略该值
  - -99999 = 重置为0
- `EMSX_STOP_PRICE` - 止损价 (-1 = 清除)
- `EMSX_ACCOUNT` - 账户
- `EMSX_EXCHANGE_DESTINATION` - 交易所目的地
- `EMSX_NOTES` - 备注
- `EMSX_CLEARING_ACCOUNT` - 清算账户
- `EMSX_CLEARING_FIRM` - 清算公司
- `EMSX_COMM_TYPE` - 佣金类型
- `EMSX_USER_COMM_RATE` - 用户佣金费率
- `EMSX_USER_FEES` - 用户费用
- `EMSX_GTD_DATE` - GTD日期
- `EMSX_ODD_LOT` - 零股标识
- `EMSX_P_A` - Principal/Agent
- `EMSX_LOC_BROKER` - 本地经纪商
- `EMSX_LOC_ID` - 本地ID
- `EMSX_LOC_REQ` - 本地请求标识

**策略参数** (`EMSX_STRATEGY_PARAMS`):
- `EMSX_STRATEGY_NAME` - 策略名称 (如 VWAP)
- `EMSX_STRATEGY_FIELD_INDICATORS` - 字段指示器
- `EMSX_STRATEGY_FIELDS` - 策略字段值
  - StartTime - 开始时间
  - EndTime - 结束时间
  - Max%Volume - 最大成交量百分比
  - %AMSession - 上午时段百分比
  - OPG - 开盘
  - MOC - 收盘
  - CompletePX - 完成价格
  - TriggerPX - 触发价格

## UI 功能规划

### 1. 右键菜单 / 操作按钮
在 RouteTable 的每一行添加操作按钮或右键菜单：

```
┌─────────────────────────────┐
│ 取消 Route (Cancel)          │
│ 修改数量 (Modify Amount)     │
│ 修改订单类型 (Modify Type)   │
│ 修改限价 (Modify Limit Price)│
│ 修改策略 (Modify Strategy)   │
│ 更改 Broker (Change Broker)  │
└─────────────────────────────┘
```

### 2. 取消 Route 弹窗
- 确认对话框
- 显示 Route 信息（Sequence, RouteID, Ticker, Status）
- 确认按钮调用 CancelRouteEx

### 3. 修改数量弹窗
- 输入新数量
- 显示当前数量
- 验证：新数量必须大于等于已成交数量

### 4. 修改订单类型弹窗
- 下拉选择：MKT, LMT, STP, STOP_LIMIT
- 如果选择 LMT，显示限价输入框
- 如果选择 STP/STOP_LIMIT，显示止损价输入框

### 5. 修改策略弹窗
- 策略选择：VWAP, TWAP, POV 等
- 策略参数表单：
  - 开始时间
  - 结束时间
  - 最大成交量百分比
  - 其他参数

### 6. 更改 Broker 弹窗
- Broker 选择下拉框
- 显示当前 Broker
- 可选：更改 Exchange Destination

## 状态管理

### Route 可修改状态
根据 EMSX API，以下状态的 Route 可以修改：
- `SENT` - 已发送
- `WORKING` - 工作中
- `PARTFILL` - 部分成交
- `QUEUED` - 队列中
- `HOLD` - 暂停

### 不可修改的状态
- `FILLED` - 已完全成交
- `CANCEL` - 已取消
- `DONE` - 已完成
- `REJECTED` - 被拒绝
- `BUST` - 已冲销

## API 响应处理

### 成功响应
- 显示成功消息
- 刷新 Route 列表

### 错误响应
- 显示错误详情
- 常见错误：
  - Route 状态不允许修改
  - 参数验证失败
  - 执行场所拒绝

## 实现注意事项

1. **用户确认**: 所有修改操作都需要用户确认
2. **状态检查**: 提交前检查 Route 状态是否允许修改
3. **参数验证**: 客户端验证必填字段
4. **错误处理**: 显示详细的错误信息
5. **刷新机制**: 操作成功后刷新 Route 数据

## 后端 API 端点建议

```
POST /api/routes/cancel
{
  "sequence": number,
  "routeId": number
}

POST /api/routes/modify
{
  "sequence": number,
  "routeId": number,
  "amount"?: number,
  "orderType"?: string,
  "limitPrice"?: number,
  "stopPrice"?: number,
  "tif"?: string,
  "strategyParams"?: object
}
```

## 参考文档
- EMSX API Developer's Guide: ModifyRouteEx (Line 5532)
- EMSX API Developer's Guide: CancelRouteEx (Line 1918)
