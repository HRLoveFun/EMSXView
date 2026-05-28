# EMSXView 前后端 API 通信接口契约

> **文档版本**: 1.0.0  
> **创建日期**: 2026-05-28  
> **适用范围**: 前端 `frontend/` ↔ 后端 `backend/api/`  
> **通信方式**: RESTful API + WebSocket

---

## 目录

1. [通信架构](#1-通信架构)
2. [标准响应格式](#2-标准响应格式)
3. [认证机制](#3-认证机制)
4. [端点总览](#4-端点总览)
5. [Core 路由详述](#5-core-路由详述)
6. [WebSocket 实时流](#6-websocket-实时流)
7. [NDJSON 批量流式接口](#7-ndjson-批量流式接口)
8. [错误码规范](#8-错误码规范)
9. [共享枚举](#9-共享枚举)

---

## 1. 通信架构

```
┌──────────────────────┐       HTTP/HTTPS (REST)        ┌──────────────────────┐
│    Frontend (React)   │ ◄─────────────────────────────► │   Backend (FastAPI)   │
│    frontend/           │         /api/*                 │   backend/api/        │
│                        │                                │                       │
│    Auth: JWT Token     │       WebSocket               │   Port: 3000           │
│    stored in            │ ◄─────────────────────────────► │                       │
│    localStorage         │         /ws/*                 │                       │
└──────────────────────┘                                └──────────────────────┘
```

### 开发环境

| 配置项 | 前端口址 | 后端地址 |
|--------|----------|----------|
| Dev Server | `http://localhost:5173` | `http://localhost:3000` |
| WebSocket | `ws://localhost:5173/ws/orders` (Vite proxy) | `ws://localhost:3000/ws/orders` |

- Vite 开发服务器将 `/api/*` 和 `/ws/*` 代理到后端 `http://localhost:3000`
- 前端通过 `VITE_API_URL` 环境变量控制 API 基础路径

### 生产环境 (Docker + Nginx)

```
Browser → Nginx (:80) → Frontend (static files)
                       → /api/* → Backend (:3000)
                       → /ws/*  → Backend (:3000)
```

---

## 2. 标准响应格式

### 成功响应

```json
{
  "success": true,
  "data": { /* 业务数据 */ },
  "message": "操作成功描述",
  "timestamp": "2026-05-28T14:30:00"
}
```

### 错误响应

```json
{
  "success": false,
  "error": "错误描述",
  "data": null,
  "message": null,
  "timestamp": "2026-05-28T14:30:00"
}
```

### 前端类型定义

```typescript
// frontend/src/shared/types/index.ts
export interface ApiResponse<T> {
  success: boolean;
  data?: T;
  error?: string;
  message?: string;
}
```

### 后端 Schema (Pydantic v2)

```python
# backend/api/schemas/common.py
class ApiResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    message: Optional[str] = None
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
```

---

## 3. 认证机制

### JWT Bearer Token

所有 API 端点（标记为 `🔒`）需要 JWT 认证，公开端点（标记为 `🌐`）无需认证。

**流程**:
1. `POST /api/auth/login` 获取 `access_token`
2. 前端存储 token 于 `localStorage` (key: `emsx_token`)
3. 后续请求 Header: `Authorization: Bearer <token>`

**Token 配置**:
- 算法: HS256
- 有效期: 默认 480 分钟 (8 小时)
- 密钥: `JWT_SECRET` 环境变量

**前端 Token 管理** (`frontend/src/shared/services/token-service.ts`):
```typescript
export const tokenService = {
  setToken: (token: string) => localStorage.setItem('emsx_token', token),
  getToken: () => localStorage.getItem('emsx_token'),
  clearToken: () => localStorage.removeItem('emsx_token'),
};

export function getAuthHeaders(): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  return headers;
}
```

---

## 4. 端点总览

### Core Routers (始终加载)

| 路由模块 | 前缀 | 认证 | 端点数 | 说明 |
|----------|------|------|--------|------|
| Connection | `/` | 混合 | 5 | 服务信息、健康检查、Bloomberg 连接 |
| Auth | `/api/auth` | 混合 | 1 | 用户登录认证 |
| Orders | `/api/orders`, `/api/executions` | 🔒 | 11 | 订单 CRUD、批量路由、父执行管理 |
| Routes | `/api/routes` | 🔒 | 5 | 路由管理（查询/修改/取消） |
| Broker | `/api/broker` | 🔒 | 4 | 券商算法配置 |
| Route Plans | `/api/route-plans` | 🔒 | 3 | 路由计划管理 |
| Market Broker Mapping | `/api/market-broker-mapping` | 🔒 | 2 | 市场-券商映射配置 |
| MarketView | `/api/marketview` | 🔒 | 2 | 市场快照数据 |
| Realtime | `/ws` | 🔒 | 1 | WebSocket 实时订单/路由流 |
| Debug | `/api/debug` | 🔒 | 2 | 调试端点 |

### Optional Routers (可选加载，异常不影响核心功能)

| 路由模块 | 前缀 | 说明 |
|----------|------|------|
| CostView | `/api/tca`, `/api/costview` | TCA 分析、评分卡、制度分布 |
| DatabaseView | `/api/db` | 数据库概览、表管理、数据完整性 |
| Execution History | `/api/history` | 历史执行记录查询 |

---

## 5. Core 路由详述

### 5.1 Connection Router (`🌐` / `🔒`)

| 方法 | 路径 | 认证 | 说明 |
|------|------|------|------|
| GET | `/` | 🌐 | API 根路径 — 服务信息、版本 |
| GET | `/api/health` | 🌐 | 健康检查（Bloomberg + 数据库状态） |
| GET | `/api/connection` | 🔒 | Bloomberg 连接状态详情 |
| GET | `/api/startup-status` | 🔒 | 分层启动状态（backend → Bloomberg → 订阅就绪） |
| POST | `/api/connection/reconnect` | 🔒 | 强制重连 Bloomberg |

**启动状态快照 (StartupStatusSnapshot)**:
```json
{
  "phase": "ready",
  "ready": true,
  "message": "All systems operational",
  "backend": { "httpReady": true, "uptime": 120 },
  "bloomberg": { "status": "connected", "lastConnected": "..." },
  "subscriptions": { "ordersInitPaintDone": true, "routesInitPaintDone": true, "ready": true }
}
```

### 5.2 Auth Router (`🔒`)

| 方法 | 路径 | 认证 | 请求体 | 说明 |
|------|------|------|--------|------|
| POST | `/api/auth/login` | 🌐 | `{ username, password }` | 返回 `{ access_token, token_type, user }` |

### 5.3 Orders Router (`🔒`)

#### 订单查询/管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/orders/status` | 订单订阅状态 |
| GET | `/api/orders?symbol=&side=&status=&orderType=&trader=...` | 查询订单（支持多条件过滤） |
| GET | `/api/orders/refresh` | 强制刷新订单列表 |
| POST | `/api/orders/modify` | 修改单个订单 |
| POST | `/api/orders/route` | 路由订单到券商（含合规检查） |
| POST | `/api/orders/{order_id}/cancel` | 取消订单 |

#### 批量操作

| 方法 | 路径 | 响应类型 | 说明 |
|------|------|----------|------|
| POST | `/api/orders/batch-update` | JSON | 批量更新多订单 |
| POST | `/api/orders/batch-route` | JSON / NDJSON | 批量路由（dryRun=true 返回 JSON，false 返回 NDJSON 流） |

#### 父级执行 (算法交易)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/executions` | 创建父级算法执行（TWAP/VWAP/POV） |
| GET | `/api/executions` | 列出所有活动执行 |
| GET | `/api/executions/{parent_id}` | 获取父级执行状态 |
| POST | `/api/executions/{parent_id}/command` | 控制命令（PAUSE/RESUME/CANCEL） |

### 5.4 Routes Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/routes?orderId=` | 查询路由（可选按订单 ID 过滤） |
| POST | `/api/routes/modify` | 修改单个路由 |
| POST | `/api/routes/{route_id}/cancel` | 取消单个路由 |
| POST | `/api/routes/batch-modify` | 批量修改路由（NDJSON 流） |
| POST | `/api/routes/batch-cancel` | 批量取消路由（NDJSON 流） |

### 5.5 Broker Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/broker/algorithms` | 获取券商算法列表（JSON 文件缓存） |
| GET | `/api/broker/algorithms?broker=&asset=` | 按券商/资产过滤算法 |
| GET | `/api/broker/strategies` | 获取所有算法策略 |
| GET | `/api/broker/strategies/{strategy_id}` | 获取特定策略详情 |

### 5.6 Route Plans Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/route-plans` | 获取所有路由计划 |
| POST | `/api/route-plans` | 创建路由计划 |
| PUT | `/api/route-plans/{plan_id}` | 更新路由计划 |

### 5.7 Market Broker Mapping Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/market-broker-mapping` | 获取市场-券商映射数据 |
| POST | `/api/market-broker-mapping` | 更新市场-券商映射数据 |

### 5.8 MarketView Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/marketview/snapshot?pool_id=&limit=&sort_by=` | 市场快照数据 |
| GET | `/api/marketview/intraday-features?tickers=&bucket_minutes=` | 日内特征数据 |

### 5.9 Debug Router (`🔒`)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/debug/memory` | 内存诊断信息 |
| GET | `/api/debug/subscription-state` | EMSX 订阅状态详情 |

---

## 6. WebSocket 实时流

### 连接

```
ws://localhost:3000/ws/orders
```

### 协议

基于 JSON 消息的双向通信，支持心跳保活和游标恢复。

### 消息类型

#### 服务端 → 客户端

| type | 说明 | 示例 |
|------|------|------|
| `connected` | 握手成功 | `{ "type": "connected", "cursor": 42, "timestamp": "..." }` |
| `replay_done` | 游标追赶完成 | `{ "type": "replay_done", "replayed": 5, "cursor": 42 }` |
| `snapshot` | 初始全量数据 | `{ "type": "snapshot", "entity": "order", "key": "123", "data": {...} }` |
| `update` | 增量更新 | `{ "type": "update", "entity": "route", "key": "456", "data": {...} }` |
| `delete` | 实体删除 | `{ "type": "delete", "entity": "order", "key": "123" }` |
| `pong` | 心跳响应 | `{ "type": "pong" }` |

#### 客户端 → 服务端

| action | 说明 |
|--------|------|
| `{ "action": "ping" }` | 心跳 |
| `{ "action": "replay", "cursor": 42 }` | 请求游标追赶 |

### 前端实时客户端

```typescript
// frontend/src/shared/services/realtime.ts
import { createRealtimeClient } from '@shared/services/realtime';

const client = createRealtimeClient({ url: 'ws://localhost:3000/ws/orders' });

client.on('order', (event) => { /* 处理订单更新 */ });
client.on('route', (event) => { /* 处理路由更新 */ });
client.onStatus((status) => { /* connecting | connected | disconnected */ });

client.connect();
// client.forceReconnect();  // 强制重连（页面可见性恢复）
// client.disconnect();
```

### 连接参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| heartbeatMs | 15000 | 心跳间隔 (ms) |
| maxReconnects | 0 | 最大重连次数 (0 = 无限) |
| reconnectBaseMs | 1000 | 重连基础延迟 (指数退避，上限 30s) |

---

## 7. NDJSON 批量流式接口

批量操作接口（`/api/orders/batch-route`, `/api/routes/batch-modify`, `/api/routes/batch-cancel`）使用 `application/x-ndjson` 流式响应。

### 响应格式

```
{"status":"success","orderId":"123","message":"Routed to BROKER_A","details":{...}}
{"status":"blocked","orderId":"456","message":"Compliance check failed","details":{...}}
{"summary":{"total":2,"succeeded":1,"blocked":1,"failed":0}}
```

每行是一个独立的 JSON 对象，最后一行包含 `summary` 汇总对象。

### 前端消费

```typescript
import { streamNdjsonBatch } from '@execution/services/http-client';

await streamNdjsonBatch('/api/orders/batch-route', payload,
  (item) => { /* 处理每项结果 */ },
  (summary) => { /* 处理汇总 */ }
);
```

---

## 8. 错误码规范

| HTTP 状态码 | 含义 | 处理方式 |
|------------|------|----------|
| 200 | 成功 | 读取 `data` 字段 |
| 400 | 请求参数错误 / 合规检查失败 | 读取 `error` 字段 |
| 401 | 未认证 | 清除 token，提示重新登录 |
| 403 | 无权限（非允许交易者） | 显示权限错误 |
| 500 | 服务器内部错误 | 显示通用错误信息 |
| 502 | Backend 不可用 (Bloomberg) | 显示 Bloomberg 连接错误（前端自动重试） |
| 503 | 服务不可用 | 显示后端离线信息 |
| 504 | 网关超时 | 显示超时信息 |

### 前端错误处理策略

```typescript
// frontend/src/modules/execution/services/http-client.ts
async function apiFetch<T>(path: string, options?: RequestInit): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: { ...getAuthHeaders(), ...(options.headers ?? {}) },
  });

  if (!response.ok) {
    if (response.status === 401) {
      tokenService.clearToken();
      return { success: false, error: 'Authentication expired' };
    }
    if (response.status >= 502 && response.status <= 504) {
      if (errorMsg.includes('Bloomberg')) {
        return { success: false, error: errorMsg };
      }
      return { success: false, error: 'Backend unavailable' };
    }
    return { success: false, error: errorMsg };
  }

  const data = await response.json();
  return data as ApiResponse<T>;
}
```

---

## 9. 共享枚举

前后端共享以下枚举值，保持类型一致性：

### OrderSide
| 前端 (TypeScript) | 后端 (Python) |
|------------------|--------------|
| `"BUY"` | `OrderSide.BUY` |
| `"SELL"` | `OrderSide.SELL` |

### OrderStatus
| 值 |
|-----|
| `NEW`, `ASSIGN`, `WORKING`, `PARTIAL`, `FILLED`, `CANCELLED`, `PENDING_CANCEL`, `REJECTED`, `COMPLETED`, `QUEUED`, `SENT`, `SUSPENDED` |

### OrderType
| 值 |
|-----|
| `LIMIT`, `MARKET`, `STOP`, `STOP_LIMIT` |

### TimeInForce
| 值 |
|-----|
| `DAY`, `GTC`, `IOC`, `FOK`, `GTX`, `GTD` |

### RouteStatus
| 值 |
|-----|
| `SENT`, `WORKING`, `PARTFILLED`, `FILLED`, `CANCEL`, `CXLREQ`, `CXLREJ`, `CXLREP`, `CXLRPRQ`, `CXLRPRJ`, `REJECTED`, `DONE`, `QUEUED`, `HOLD`, `BUST`, `CORRECTED`, `REPPEN`, `ROUTE-ERR`, `OMS-PEND`, `A-SENT`, `ALLOCATED`, `OA-SENT` |

---

## 附录：前后端目录结构

```
EMSXView/
├── frontend/                       # 独立前端项目
│   ├── src/
│   │   ├── shared/
│   │   │   ├── services/           # 共享服务（realtime, token-service）
│   │   │   └── types/              # ApiResponse 等共享类型
│   │   └── modules/               # 业务模块（各自调用 /api/* 端点）
│   ├── vite.config.ts             # /api/*, /ws/* → localhost:3000 代理
│   └── package.json
│
├── backend/                        # 独立后端项目
│   ├── api/
│   │   ├── main.py                # FastAPI 入口
│   │   ├── routers/               # API 路由定义
│   │   ├── services/              # 业务逻辑
│   │   └── schemas/               # Pydantic 数据模型
│   ├── config/                    # Nginx, Prometheus, Grafana
│   └── docker-compose.yml         # 生产部署编排
│
└── docs/
    └── api-contracts.md           # 本文档 — API 契约规范
```

---

> **维护说明**: 新增 API 端点或修改现有端点 Schema 时，请同步更新本文档。前后端共享枚举值的修改需在两端保持一致性。
