# Error Patterns & Resolution Log

> 高频问题记录、根因分析与解决方案知识库。
> 目标：避免重复踩坑，缩短问题定位时间。

---

## 工具定位与使用说明

### 这是什么？

这是一个**结构化错误知识库**，专门记录 AI 辅助编程过程中反复出现的问题模式。与 `HANDOFF.md`（会话状态）和 `MEMORY.md`（架构决策）不同，本文档聚焦于：

- **可复现的错误模式**（Error Patterns）
- **根因分析**（Root Cause）
- **经过验证的解决方案**（Verified Solutions）
- **预防措施**（Prevention）

### 什么时候使用？

| 场景 | 操作 |
|------|------|
| 遇到报错时 | 先搜索本文档，查看是否有匹配的模式 |
| 解决了一个棘手问题后 | 记录到本文档，避免下次重复踩坑 |
| 发现某类错误反复出现（≥2次） | 升级为"高频模式"，完善根因分析 |
| 规划新功能时 | 查阅相关技术栈的常见坑点 |

### 如何查找？

1. **快速搜索**：使用 IDE 或终端搜索错误关键词
   ```bash
   # 在项目内搜索错误信息
   grep -r "EMSX_CURRENCY" docs/ --include="*.md"
   ```

2. **按技术栈浏览**：查看目录中的分类标签

3. **按症状匹配**：根据错误表现找到对应条目

---

## 记录格式

每个错误条目遵循以下模板：

```markdown
### [ERR-XXX] 简短错误描述

**分类**: `分类标签`
**出现次数**: N 次 | **最后出现**: YYYY-MM-DD
**相关技术栈**: Python/TypeScript/EMSX API/etc.

#### 症状表现
错误信息、异常堆栈、或异常行为的精确描述。

#### 根因分析
为什么会发生？涉及哪些机制或约束？

#### 解决方案
经过验证的修复步骤或代码示例。

#### 预防措施
如何避免再次发生？配置检查、代码审查点等。

#### 相关条目
- 链接到其他相关错误条目
```

---

## 错误条目

### [ERR-001] EMSX_CURRENCY 字段无效

**分类**: `API-FIELD`  
**出现次数**: 2 次 | **最后出现**: 2026-02-24  
**相关技术栈**: Bloomberg EMSX API, Python

#### 症状表现
```
Error: Invalid field name detected. Field=|EMSX_CURRENCY|
```
后端日志显示字段订阅失败，但 GUIDE 文档中确实存在该字段名。

#### 根因分析
EMSX API 字段名与 GUIDE 文档存在不一致。`EMSX_CURRENCY` 可能已被废弃或改名为 `EMSX_CRNCY`，但文档未及时更新。这属于 Bloomberg API 的常见问题——字段命名在不同版本或不同服务（`emapisvc` vs `emapisvc_beta`）中可能存在差异。

#### 解决方案
1. 从订阅字段列表中移除 `EMSX_CURRENCY`
2. 如需货币信息，通过订单中的 `EMSX_TICKER` 或 `EMSX_ISIN` 关联获取
3. 交叉验证所有字段名，参考实际日志输出而非仅依赖 GUIDE

#### 预防措施
- **字段添加检查清单**：
  - [ ] 查阅 GUIDE 确认字段存在
  - [ ] 在测试环境验证字段有效性
  - [ ] 查看后端日志确认无 `Invalid field name` 错误

#### 相关条目
- [ERR-002] 新字段添加导致订阅失败

---

### [ERR-002] 新字段添加导致订阅失败

**分类**: `API-FIELD`  
**出现次数**: 1 次 | **最后出现**: 2026-02-24  
**相关技术栈**: Bloomberg EMSX API, Python

#### 症状表现
添加新字段到订阅列表后，Bloomberg 连接断开或订单数据不再更新。

#### 根因分析
EMSX API 采用字段白名单机制。无效的字段会导致整个订阅请求失败，而非仅忽略该字段。这是 blpapi 库的行为特性。

#### 解决方案
1. 每次只添加一个字段，验证后再添加下一个
2. 使用 `//blp/emapisvc_beta` 服务测试新字段
3. 检查日志中的 `Invalid field name` 错误

#### 预防措施
- 批量修改字段前先备份当前配置
- 在 `main.py` 中注释说明每个字段的验证日期

#### 相关条目
- [ERR-001] EMSX_CURRENCY 字段无效

---

### [ERR-003] EMSX API 未在 EMSS 中启用

**分类**: `CONFIG`  
**出现次数**: 3+ 次 | **最后出现**: 2026-03-16  
**相关技术栈**: Bloomberg Terminal, EMSX API

#### 症状表现
```
Error: Not enabled for EMSX API in EMSS
```
后端健康检查显示连接失败，即使 Bloomberg Terminal 已运行。

#### 根因分析
Bloomberg 终端需要在 EMSS (Enterprise Multi-Server System) 配置中显式启用 EMSX API 权限。这是 IT 管理员控制的配置项，与终端是否运行无关。

#### 解决方案
1. 确认 Bloomberg Terminal 已登录
2. 联系 IT 部门启用 EMSX API 权限
3. 等待配置生效后重启后端服务

#### 预防措施
- 在 `CLAUDE.md` 中记录 IT 联系人
- 在部署文档中明确此为前置依赖项

#### 相关条目
- [ERR-004] Bloomberg 连接超时

---

### [ERR-004] Bloomberg 连接超时

**分类**: `NETWORK`  
**出现次数**: 1 次 | **最后出现**: 2026-02-24  
**相关技术栈**: Bloomberg API, 网络配置

#### 症状表现
```
Connection timeout after 30000ms
```
后端无法建立与 Bloomberg 终端的连接。

#### 根因分析
可能原因：
1. Bloomberg Terminal 未运行
2. 防火墙阻止端口 8194
3. `BLOOMBERG_HOST` 配置错误（应使用 `localhost` 而非 IP）
4. EMSX API 未启用（见 [ERR-003]）

#### 解决方案
1. 检查终端是否运行并登录
2. 验证 `.env` 中的主机配置
3. 尝试 telnet 测试端口连通性
4. 联系 IT 检查防火墙设置

#### 预防措施
- 在 `api/health` 端点中增加连接状态检查
- 添加更详细的错误日志区分不同原因

#### 相关条目
- [ERR-003] EMSX API 未在 EMSS 中启用

---

### [ERR-005] TypeScript 类型与后端不同步

**分类**: `TYPE-SYNC`  
**出现次数**: 2 次 | **最后出现**: 待定  
**相关技术栈**: TypeScript, Python, FastAPI, Pydantic

#### 症状表现
```
Type error: Property 'xxx' does not exist on type 'Order'
```
或运行时 API 调用成功但前端类型检查失败。

#### 根因分析
后端 Pydantic 模型修改后，前端 TypeScript 类型未同步更新。这是全栈开发中的常见同步问题。

#### 解决方案
1. 修改 `emsx-backend/backend/main.py` 中的 Pydantic 模型
2. 同步更新 `app/src/types/index.ts` 中的对应类型
3. 运行 `npm run lint` 验证类型一致性

#### 预防措施
- 在 `CLAUDE.md` 的 "Add EMSX API Field" 任务中包含类型同步步骤
- 考虑使用 openapi-typescript 自动生成类型

#### 相关条目
无

---

### [ERR-006] WebSocket 连接断开未重连

**分类**: `STATE-MGMT`  
**出现次数**: 1 次 | **最后出现**: 待定  
**相关技术栈**: React, WebSocket, FastAPI

#### 症状表现
前端在 WebSocket 断开后不再接收实时更新，需要手动刷新页面。

#### 根因分析
WebSocket 连接未实现自动重连机制。网络波动或后端重启会导致连接永久丢失。

#### 解决方案
在 `app/src/services/websocket.ts` 中实现重连逻辑：
- 监听 `onclose` 事件
- 指数退避重试
- 最大重试次数限制

#### 预防措施
- 将 WebSocket 封装为 Hook 统一处理生命周期
- 添加连接状态 UI 指示器

#### 相关条目
无

---

### [ERR-007] Broker-Algorithms Refresh 阻塞后端事件循环导致全局超时

**分类**: `ASYNC-BLOCKING`  
**出现次数**: 1 次 | **最后出现**: 2026-03-17  
**相关技术栈**: Python, FastAPI, Uvicorn, asyncio, Bloomberg blpapi

#### 症状表现
前端显示 "Disconnected"，所有 API 请求（包括 `/api/connection`）超时。触发条件：`POST /api/broker-algorithms/refresh` 正在执行时，其他端点完全无响应。测试表明 `/api/connection` 在 refresh 期间耗时 10,046ms 后超时。

#### 根因分析
`EMSXService._send_request()` 是同步阻塞方法（内部使用 `session.nextEvent()` 循环等待 Bloomberg 响应）。所有 FastAPI async 路由处理函数直接调用该方法，导致 Uvicorn 的单线程 asyncio 事件循环被阻塞。

`/api/broker-algorithms/refresh` 端点会级联调用：
1. `get_brokers()` — 1 次 Bloomberg 请求
2. `get_broker_strategies()` — 每个 broker 1 次（约 15 个 broker）
3. `get_broker_strategy_info()` — 每个 strategy 1 次（约 70+ 个 strategy）

总计 90+ 次 **同步阻塞** Bloomberg API 调用，占用事件循环数分钟，期间所有其他请求被排队等待。

#### 解决方案
1. 新增 `_send_request_async()` 异步包装方法，使用 `asyncio.run_in_executor(None, ...)` 将同步 Bloomberg 调用移至线程池：
   ```python
   async def _send_request_async(self, request):
       loop = asyncio.get_event_loop()
       return await loop.run_in_executor(None, self._send_request, request)
   ```
2. 将所有 8 个调用 `_send_request()` 的方法替换为 `await self._send_request_async(request)`：
   - `modify_order`, `cancel_order`, `cancel_route`, `modify_route`
   - `route_order`, `get_broker_strategies`, `get_broker_strategy_info`, `get_brokers`

修复后验证：refresh 执行期间 `/api/connection` 响应时间 ~2 秒（GIL 竞争导致的合理延迟），远优于修复前的 10+ 秒超时。

#### 预防措施
- **规则**：在 FastAPI async 处理函数中永远不要直接调用同步阻塞方法，必须通过 `run_in_executor` 包装
- 可考虑增加 Uvicorn worker 数（当前 `API_WORKERS: 1`）以进一步降低延迟
- 添加 refresh 任务进度追踪端点，让前端可以展示 refresh 进度

#### 相关条目
- [ERR-004] Bloomberg 连接超时
- [ERR-008] useBrokerAlgorithms Hook isLoading 状态永久锁定

---

### [ERR-008] useBrokerAlgorithms Hook isLoading 状态永久锁定

**分类**: `STATE-MGMT`  
**出现次数**: 2 次 | **最后出现**: 2026-03-17  
**相关技术栈**: React, TypeScript, Custom Hooks

#### 症状表现
1. **Settings Tab**：页面永远显示 "Loading broker algorithms..." spinner，无法加载 broker 树形视图
2. **Route Order Panel**：Broker 和 Algorithm 下拉菜单处于禁用/不可交互状态

两个问题在 Bloomberg 连接异常或首次加载数据失败时必定出现。

#### 根因分析
`useBrokerAlgorithms` hook 的 `refreshData` 方法中，catch 块只重置了 `isRefreshing: false`，**遗漏了** `isLoading: false`：

```typescript
// 修复前 (BUG)
} catch (error) {
  setState(prev => ({
    ...prev,
    isRefreshing: false,  // ✓
    error: '...'
    // isLoading: false  ← 缺失！
  }));
}
```

当 hook 初始化时设置 `isLoading: true` 并调用 `refreshData()`，如果 refresh 失败（如 Bloomberg 未连接、后端超时），`isLoading` 永远停留在 `true`，导致所有依赖该 hook 的 UI 组件卡在加载状态。

#### 解决方案
1. 在 `refreshData` catch 块中补充 `isLoading: false`：
   ```typescript
   } catch (error) {
     setState(prev => ({
       ...prev,
       isLoading: false,     // ← 新增
       isRefreshing: false,
       error: '...'
     }));
   }
   ```
2. 在 `order-route-dialog.tsx` 中添加 on-demand strategy 获取逻辑，当 hook 数据不可用时通过 `cachedApiService.getBrokerStrategies()` 按需加载
3. 添加 fallback：refresh 失败后尝试通过 `GET /api/brokers` 获取最小 broker 列表

#### 预防措施
- **规则**：任何 hook 中设置 `isLoading: true` 的地方，必须确保所有代码路径（包括 catch/finally）都能将其还原为 `false`
- 可考虑使用 `finally` 块统一处理 loading 状态重置
- 添加 loading 超时机制（如 30 秒后自动重置）作为安全网

#### 相关条目
- [ERR-007] Broker-Algorithms Refresh 阻塞后端事件循环导致全局超时

---

### [ERR-009] Bloomberg Session 共享导致 Request/Response 超时

**分类**: `SESSION-SHARING`  
**出现次数**: 1 次 | **最后出现**: 2026-03-17  
**相关技术栈**: Python, Bloomberg blpapi, FastAPI

#### 症状表现
所有 Bloomberg request/response API 端点（`/api/brokers`、`/api/broker-strategies`、`/api/broker-algorithms/refresh`）超时（30s+），尽管 `run_in_executor` 已解决事件循环阻塞。`broker_algorithms.json` 文件仅 90 字节（空 configs）。Refresh 日志显示大量 `504: Bloomberg request timed out` 错误。

#### 根因分析
`_send_request()` 和订阅线程（`_subscription_loop`）共用同一个 `self.session` 对象。两者都调用 `session.nextEvent()` 从同一事件队列中读取事件。Bloomberg `nextEvent()` 是消费性的——事件被一个调用者读取后，另一个调用者永远看不到。

结果：订阅线程持续轮询事件（500ms 超时），会"偷走" request/response 的 `PARTIAL_RESPONSE` 和 `RESPONSE` 事件，导致 `_send_request()` 永远等不到响应。

关键代码路径：
```
订阅线程: while True: event = self.session.nextEvent(500)  ← 偷走响应
请求方法: event = self.session.nextEvent(5000)             ← 永远收不到
```

#### 解决方案
创建专用 `_request_session`（独立的 Bloomberg Session 对象），用于所有 request/response 操作：

```python
# __init__ 中:
self._request_session: Optional[Session] = None
self._request_service: Optional[Service] = None

# connect() 中:
self._request_session = Session(self.session_options)
self._request_session.start()
self._request_session.openService("//blp/emapisvc")
self._request_service = self._request_session.getService("//blp/emapisvc")

# _send_request() 中:
session = self._request_session or self.session
session.sendRequest(request)
event = session.nextEvent(timeout_ms)
```

同时替换所有 `self.service.createRequest()` → `self._req_service.createRequest()`（8 处调用）。

修复后验证：`/api/brokers` 390ms（之前 30s+ 超时），`/api/broker-strategies` 331ms，refresh 完成 109s 产出 95 configs（之前全部超时）。

#### 预防措施
- **规则**：Bloomberg Session 对象必须按用途隔离——订阅一个 session，请求一个 session，市场数据一个 session
- `nextEvent()` 是消费性操作，两个线程不能在同一 session 上竞争
- 当前架构：`self.session`（订阅）、`self._request_session`（请求）、`self._mktdata_session`（市场数据）
- 添加新的 Bloomberg 调用时，必须选择正确的 session

#### 相关条目
- [ERR-007] Broker-Algorithms Refresh 阻塞后端事件循环导致全局超时

---

### [ERR-010] EMSX_STATUS 未映射导致订单状态显示为 "NEW"

**分类**: `STATUS-MAPPING`  
**出现次数**: 2+ 次 | **最后出现**: 2026-03-17  
**相关技术栈**: Python, Bloomberg EMSX API

#### 症状表现
已发送到经纪商的订单（实际状态为 "SENT" 或 "A-SENT"）在前端显示为 "NEW"。后端日志出现 `Unmapped EMSX_STATUS 'SENT' for seq=XXXXXXX, defaulting to NEW` 和 `Unmapped EMSX_STATUS 'A-SENT'` 警告。

#### 根因分析
`STATUS_MAP` 字典仅包含部分 Bloomberg EMSX 状态码。Bloomberg 返回的 `EMSX_STATUS` 字段值比预期更多。当遇到未映射的状态时，`_parse_order_message` 默认回退为 "NEW"：

```python
# 原代码:
status = self.STATUS_MAP.get(raw_status, "NEW")
```

缺失的状态包括：`SENT`、`A-SENT`、`ROUTED`、`ACTIVE`、`PENDING`、`PEND-NEW`。

#### 解决方案
扩展 `STATUS_MAP` 添加缺失的映射：

```python
STATUS_MAP = {
    # ... existing entries ...
    "SENT": "SENT",       # 已发送到经纪商
    "A-SENT": "SENT",     # 自动发送
    "ROUTED": "WORKING",  # 已路由
    "ACTIVE": "WORKING",  # 活跃执行中
    "PENDING": "NEW",     # 待处理
    "PEND-NEW": "NEW",    # 待处理新单
}
```

同时更新前端：
- `types/index.ts`: `OrderStatus` 类型添加 `'SENT'`
- `OrderTable.tsx` 和 `MonitorBoard.tsx`: 添加 SENT badge 样式（sky-500）
- `routable_statuses`: 添加 `"SENT"` 和 `"QUEUED"`

修复后验证：新会话日志中零 "Unmapped EMSX_STATUS" 警告。

#### 预防措施
- **规则**：发现 `Unmapped EMSX_STATUS` 日志警告时，立即添加映射，不要让默认值掩盖问题
- 可考虑添加完整的 Bloomberg EMSX 状态列表作为参考注释
- 前端 `OrderStatus` 类型必须与后端 `STATUS_MAP` 的输出值集合保持同步（参考 [ERR-005]）

#### 相关条目
- [ERR-005] TypeScript 类型与后端不同步

---

## 快速参考表

### 按分类索引

| 分类 | 条目数 | 条目 |
|------|--------|------|
| `API-FIELD` | 2 | ERR-001, ERR-002 |
| `CONFIG` | 1 | ERR-003 |
| `NETWORK` | 1 | ERR-004 |
| `TYPE-SYNC` | 1 | ERR-005 |
| `STATE-MGMT` | 2 | ERR-006, ERR-008 |
| `ASYNC-BLOCKING` | 1 | ERR-007 |
| `SESSION-SHARING` | 1 | ERR-009 |
| `STATUS-MAPPING` | 1 | ERR-010 |

### 按技术栈索引

| 技术栈 | 相关条目 |
|--------|----------|
| Bloomberg EMSX API | ERR-001, ERR-002, ERR-003, ERR-004, ERR-007, ERR-009, ERR-010 |
| Python/FastAPI | ERR-001, ERR-002, ERR-003, ERR-004, ERR-005, ERR-007, ERR-009, ERR-010 |
| TypeScript/React | ERR-005, ERR-006, ERR-008 |
| WebSocket | ERR-006 |
| asyncio/Uvicorn | ERR-007 |

---

## 维护指南

### 何时添加新条目？

- [ ] 同一错误出现 **≥2 次**
- [ ] 解决耗时 **>30 分钟** 的问题
- [ ] 涉及 **外部依赖**（Bloomberg API、网络、配置）的问题
- [ ] **非直觉性**的解决方案（需要查阅文档或试错）

### 条目升级流程

```
首次出现 → 记录在 HANDOFF.md 的 "Recent Blockers"
反复出现 → 升级为 ERR-XXX 条目，完善根因分析
已验证解决 → 添加 "预防措施" 章节
相关错误 → 建立条目间链接
```

### 定期审查

每月检查一次本文档：
1. 删除已过时的条目（如 API 已更新）
2. 合并相似条目
3. 更新出现次数和最后出现日期
4. 验证解决方案是否仍然有效

---

## 集成到工作流

### 在 CLAUDE.md 中引用

在 `CLAUDE.md` 的 "Session Handoff" 部分添加：

```markdown
## Error Pattern Lookup

遇到错误时，按以下顺序查找：
1. 搜索 `docs/ERROR_PATTERNS.md` 中的错误信息
2. 查看 `HANDOFF.md` 的 "Recent Blockers"
3. 查阅 `MEMORY.md` 的相关技术栈章节
```

### 与 AI 助手的配合

当向 AI 描述问题时，可以引用本文档：

> "我遇到了 [ERR-001] 类似的问题，但字段名是 EMSX_CRNCY..."

这让 AI 能快速理解上下文，而非从零开始诊断。

---

*最后更新: 2026-03-17*
