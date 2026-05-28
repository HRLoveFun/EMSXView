# Bloomberg EMSX API 数据获取方式总结

> 基于 `docs/api/bloomberg-emsx-reference.md` 分析整理

## 概述

Bloomberg EMSX API 提供 **2 种主要的数据获取范式**：

| 方式 | 说明 | 适用场景 |
|------|------|----------|
| **Subscription（订阅）** | 实时推送数据更新 | 订单状态、路由状态实时监控 |
| **Request/Response（请求/响应）** | 主动查询并返回结果 | 配置查询、历史数据、元数据获取 |

---

## 一、Subscription（订阅）

订阅遵循 **C.R.U.D.** 原则（创建、读取、更新、删除），客户端订阅后，服务器会主动推送实时数据变更事件。

### 支持的订阅类型

| 序号 | 订阅类型 | 说明 |
|------|----------|------|
| 1 | **Order Subscription** | 实时获取订单数据的增删改查事件 |
| 2 | **Route Subscription** | 实时获取路由数据的增删改查事件 |

---

## 二、Request/Response（请求/响应）

### 2.1 数据查询类请求（7 种）

这类请求专门用于获取数据，不会产生副作用：

| 序号 | 请求名称 | 功能说明 |
|------|----------|----------|
| 1 | **GetAllFieldMetaData** | 获取所有字段的元数据信息 |
| 2 | **GetAssetClass** | 根据 ticker 获取资产类别 |
| 3 | **GetBrokerStrategiesWithAssetClass** | 获取指定经纪商的策略列表 |
| 4 | **GetBrokerStrategyInfoWithAssetClass** | 获取经纪商策略的详细参数 |
| 5 | **GetBrokersWithAssetClass** | 获取指定资产类别的已启用经纪商列表 |
| 6 | **GetFieldMetaData** | 获取指定字段的元数据信息 |
| 7 | **GetFills（EMSXHistory）** | 获取历史成交数据（最多 30 天） |

### 2.2 操作类请求（14 种）

这类请求主要用于创建、修改或取消订单/路由，操作完成后会返回操作结果：

| 序号 | 请求名称 | 功能说明 |
|------|----------|----------|
| 1 | **AssignTrader** | 重新分配交易员 |
| 2 | **CancelOrderEx** | 取消订单 |
| 3 | **CancelRouteEx** | 取消路由 |
| 4 | **CreateBasket** | 创建篮子订单 |
| 5 | **CreateOrder** | 创建订单 |
| 6 | **CreateOrderAndRouteEx** | 创建订单并自动路由 |
| 7 | **CreateOrderAndRouteManually** | 手动创建订单并路由 |
| 8 | **DeleteOrder** | 删除订单 |
| 9 | **GroupRouteEx** | 群组路由操作 |
| 10 | **ManualFill** | 手动录入成交 |
| 11 | **ModifyOrderEx** | 修改订单参数 |
| 12 | **ModifyRouteEx** | 修改路由参数 |
| 13 | **SellSideAck** | 卖方确认 |
| 14 | **SellSideReject** | 卖方拒绝 |

---

## 三、请求类型完整列表（共 21 种子类型）

| 分类 | 数量 | 子类型 |
|------|------|--------|
| 数据查询 | 7 | GetAllFieldMetaData, GetAssetClass, GetBrokerStrategiesWithAssetClass, GetBrokerStrategyInfoWithAssetClass, GetBrokersWithAssetClass, GetFieldMetaData, GetFills |
| 创建类操作 | 4 | CreateBasket, CreateOrder, CreateOrderAndRouteEx, CreateOrderAndRouteManually |
| 修改类操作 | 3 | ModifyOrderEx, ModifyRouteEx, AssignTrader |
| 取消/删除 | 3 | CancelOrderEx, CancelRouteEx, DeleteOrder |
| 路由操作 | 1 | GroupRouteEx |
| 成交相关 | 1 | ManualFill |
| 卖方交互 | 2 | SellSideAck, SellSideReject |

---

## 四、实践注意事项

### 4.1 响应消息类型命名

请求名称与响应 `messageType()` 返回值一致（均为 PascalCase），**不是** `UPPER_SNAKE_CASE`：

| 请求名（`createRequest` 参数） | 响应 `msg.messageType()` |
|:--|:--|
| `"GetAllFieldMetaData"` | `"GetAllFieldMetaData"` |
| `"GetFieldMetaData"` | `"GetFieldMetaData"` |
| `"GetAssetClass"` | `"GetAssetClass"` |
| `"GetBrokersWithAssetClass"` | `"GetBrokersWithAssetClass"` |
| `"GetBrokerStrategiesWithAssetClass"` | `"GetBrokerStrategiesWithAssetClass"` |
| `"GetBrokerStrategyInfoWithAssetClass"` | `"GetBrokerStrategyInfoWithAssetClass"` |
| `"CreateOrder"` | `"CreateOrder"` |
| `"CreateOrderAndRouteEx"` | `"CreateOrderAndRouteEx"` |
| … | … |
| 错误响应 | `"ERROR_INFO"` |

```python
# ✅ 正确
if msg.messageType() == "GetAllFieldMetaData":
    md = msg.getElement("MetaData")

# ❌ 错误 — 实际不会返回这种全大写格式
if msg.messageType() == "GET_ALL_FIELD_METADATA":
    ...
```

### 4.2 GetAllFieldMetaData 字段层级（Level）

`EMSX_LEVEL` 是**位掩码值**，不限于 1/2/3，实际分布如下：

| Level | 字段数 | 含义 |
|:--|:--|:--|
| 0 | 6 | 全局字段（MSG_TYPE, EVENT_STATUS, API_SEQ_NUM 等） |
| 1 | 37 | Order 级别 |
| 2 | 44 | Route 级别 |
| 3 | 37 | Order + Route |
| 8 | 3 | Basket 相关 |
| 9–11 | 5 | Basket 组合 |
| 17–27 | 29 | 多层次共享字段 |

完整数据见 `docs/api/emsx-field-metadata.json`。

---

## 五、总结

- **2 种主要范式**：Subscription + Request/Response
- **2 种订阅**：Order Subscription、Route Subscription
- **21 种请求子类型**：其中 7 种为纯数据查询，14 种为操作类请求
- **实时场景**优先使用 Subscription，**按需查询**使用 Request/Response
- **响应 messageType()** 返回 PascalCase 请求名，不是全大写
