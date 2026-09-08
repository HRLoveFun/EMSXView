# blpapi 功能模块全景（基于源码分析）

> 本文档基于对安装在环境中的 `blpapi` 源码（`D:\anaconda3\Lib\site-packages\blpapi`，版本 **3.25.11.1**）逐文件阅读整理，覆盖全部公开功能模块、同步/异步接口、事件处理机制、错误处理方式与支持的数据类型，并归纳官方示例与项目内使用场景。
>
> 包结构：底层为 C 扩展 `internals`（`_blpapi` 的 ctypes FFI），上层为纯 Python 包装层（`Session`/`Message`/`Element` 等），所有 Python 对象均持有 C 端 `handle` 并以 `CHandle` 管理生命周期。

---

## 1. 核心抽象总览

| 抽象 | 文件 | 职责 |
|---|---|---|
| `Session` / `ProviderSession` | `session.py` / `providersession.py` | 消费者/发布会话，与 Bloomberg 通信的主入口 |
| `AbstractSession` | `abstractsession.py` | 两类会话的公共基类（打开服务、收发请求、订阅、认证、令牌） |
| `SessionOptions` / `TlsOptions` / `Socks5Config` | `sessionoptions.py` | 连接、传输安全、SOCKS 代理、保活、慢消费者等配置 |
| `EventDispatcher` | `eventdispatcher.py` | 多线程事件派发器 |
| `Event` | `event.py` | 事件容器；按类型归类消息 |
| `Message` | `message.py` | 单条消息；字段读取入口 |
| `Element` | `element.py` | 结构化字段（读取 + 写入请求/发布） |
| `Service` / `Operation` | `service.py` | 服务元数据、创建请求、发布事件 |
| `Request` | `request.py` | 请求对象（字段填充） |
| `SubscriptionList` | `subscriptionlist.py` | 批量订阅描述 |
| `CorrelationId` | `correlationid.py` | 关联异步操作与响应 |
| `Identity` / `AuthOptions` | `identity.py` / `auth.py` | 授权身份与认证方式 |
| `Topic` / `TopicList` / `ResolutionList` | `topic.py` / `topiclist.py` / `resolutionlist.py` | 发布主题与解析 |
| `EventFormatter` | `eventformatter.py` | 构造待发布的 `Event` |
| `Schema*` / `Name` / `Constant` | `schema.py` / `name.py` / `constant.py` | 模式元数据与枚举常量 |
| `DataType` / `Datetime` / `FixedOffset` | `datatype.py` / `datetime.py` | 数据类型与日期类型 |
| `exception` | `exception.py` | 异常体系 |
| `Logger` | `logging.py` | 日志回调注册 |
| `RequestTemplate` | `requesttemplate.py` | 快照请求模板（避免重复解析） |

---

## 2. 会话管理（Session Management）

### 2.1 `AbstractSession` — 公共基类
提供两类会话共享的能力：

- **服务**：`openService(uri, identity=None)` / `openServiceAsync(uri, correlationId=None, identity=None)` — 同步/异步打开 `//blp/...` 服务；`getService(uri)` 取已打开服务。
- **请求**：`sendRequest(request, identity=None, correlationId=None, eventQueue=None, requestLabel=None)` / `sendRequestAsync(...)`。
- **订阅**：`subscribe(subscriptionList, identity=None, correlationId=None, eventQueue=None)` / `subscribeAsync(...)`；`resubscribe(...)` / `resubscribeAsync(...)`；`unsubscribe(subscriptionList)` / `unsubscribeAsync(...)`。
- **令牌与认证**：`generateToken(...)` / `generateTokenAsync(...)`；`createIdentity(...)`；`authorize(identity, ...)` / `authorizeUser(...)` / `authorizeAsync(...)`。
- **快照**：`createSnapshotRequestTemplate(...)` / `sendRequestTemplate(template, correlationId=None, identity=None, eventQueue=None)`（用于从订阅数据取快照而无需处理逐笔 tick）。
- **事件循环**：`nextEvent(timeout=0)` / `tryNextEvent()` / `dispatchEvent(event)`；`registerEventQueue(eventQueue, ...)`。
- **生命周期**：`stop()` / `stopAsync()`。

### 2.2 `Session` — 消费者会话（订阅/请求）
- 构造：`Session(options=None, eventHandler=None, eventDispatcher=None)`。
  - `eventHandler` 为 `None` → **同步模式**（用 `nextEvent` 轮询）。
  - `eventHandler` 非 `None` → **异步模式**（事件回调）。
- `start()` / `startAsync()`：阻塞/非阻塞启动，成功后产生 `Event.SESSION_STATUS`（`SessionStarted`）。
- `run()` / `runAsync()`：进入事件循环，直到会话停止（异步模式下 `runAsync` 立即返回）。
- `nextEvent(timeout=0)`：同步模式下阻塞取下一个事件（`timeout=0` 表示永久阻塞；超时返回 `Event.TIMEOUT`）。
- `tryNextEvent()`：非阻塞，无事件返回 `None`。

### 2.3 `ProviderSession` — 发布会话
- 继承 `AbstractSession`，额外提供发布能力：`registerService(uri, identity=None, options=None)` / `registerServiceAsync(...)`。
- 主题生命周期：`createTopics(topicList, ...)` / `createTopicsAsync(...)`、`getTopic(message)`、`deleteTopic(s)`、`terminateSubscriptionsOnTopic(s)`。
- 解析：`resolve(resolutionList, ...)` / `resolveAsync(...)`。
- 发布：`publish(event)`、`sendResponse(event, isPartialResponse=False)`、`flushPublishedEvents(timeoutMsecs)`。
- 取消注册：`deregisterService(serviceName)`（同时清理所有 topic 与挂起请求）。
- `ServiceRegistrationOptions`：注册优先级（`PRIORITY_LOW/MEDIUM/HIGH`）、`setGroupId`、`setServicePriority`、`addActiveSubServiceCodeRange`、`setPartsToRegister`（`PART_PUBLISHING`/`PART_OPERATIONS`/`PART_SUBSCRIBER_RESOLUTION`/`PART_PUBLISHER_RESOLUTION`）。

### 2.4 `SessionOptions` — 连接与传输配置
- 服务器：`setServerHost` / `setServerPort`（默认 `127.0.0.1:8194`）、`setServerAddress(host, port, index, socks5Config)` / `removeServerAddress(index)`、多地址支持。
- 客户端模式：`setClientMode(AUTO | DAPI | SAPI)`（AUTO=桌面优先否则服务端；DAPI=强制桌面；SAPI=强制服务端）。
- **传输安全**：`setTlsOptions(tlsOptions)`；`TlsOptions.createFromFiles(...)` / `createFromBlobs(...)`（PKCS#12 客户端凭证 + PKCS#7 信任材料）、`setTlsHandshakeTimeoutMs`、`setCrlFetchTimeoutMs`。
- **代理**：`Socks5Config(hostname, port)` + `setServerAddress(..., socks5Config=...)`。
- 保活：`setKeepAliveEnabled`、`setDefaultKeepAliveInactivityTime`（默认 20000ms）、`setDefaultKeepAliveResponseTimeout`（默认 5000ms）。
- 慢消费者：`setSlowConsumerWarningHiWaterMark`（默认 0.75）、`setSlowConsumerWarningLoWaterMark`（默认 0.5）、`setMaxEventQueueSize`（默认 10000，超出丢弃）。
- 重连与重试：`setAutoRestartOnDisconnection`、`setNumStartAttempts`、`setConnectTimeout`（默认 5000ms）。
- 默认服务：`setDefaultSubscriptionService`（默认 `//blp/mktdata`）、`setDefaultTopicPrefix`（默认 `/ticker/`）、`setAllowMultipleCorrelatorsPerMsg`。
- 会话身份：`setSessionIdentityOptions(authOptions, correlationId=None)` — 启动时自动授权，身份与会话生命周期绑定。
- 其它：`setMaxPendingRequests`（默认 1024）、`recordSubscriptionDataReceiveTimes`（开启后可用 `Message.timeReceived()`）、`setServiceCheckTimeout`/`setServiceDownloadTimeout`、`setApplicationIdentityKey`、`setSessionName`、`setBandwidthSaveModeDisabled`。

### 2.5 `EventDispatcher` — 事件分发器
- `EventDispatcher(numThreads=1)`：创建拥有独立线程池的分发器。
- `EventDispatcher.registerSession(session)` / `unregisterSession(session)`：多个会话可共享同一分发器。
- 传入 `EventDispatcher` 的 `Session` 在异步模式下，事件按序派发到 `EventHandler`（单订阅的部分响应与更新保持顺序）。

---

## 3. 订阅服务（Subscriptions）

### 3.1 `SubscriptionList`
- `add(topic, correlationId=None, options=None)`：添加订阅（topic 形如 `/ticker/IBM US Equity` 或服务前缀 URI）。
- `addResolved(...)`：仅当 topic 已解析时生效；`correlationIdAt(i)` / `topicString(correlationId)` / `topicStringAt(i)` 取回信息；`setOption(correlationId, name, value)` / `appendOption(...)` 设订阅选项（如 `fields`、`interval`）。
- `correlationId`（构造/订阅时可选）用于把响应与订阅关联。
- 订阅状态枚举（在 `Event.SUBSCRIPTION_STATUS` 中）：`SubscriptionStarted`、`SubscriptionSuccess`、`SubscriptionFailure`、`SubscriptionTerminated`、`SubscriptionStreamsActivated/Deactivated`、`DataLoss`（`Names` 常量提供对应 `Name`）。

### 3.2 典型订阅场景
- 行情（mktdata）：实时价格、买卖盘。
- **EMSX（`//blp/emapisvc`）**：本项目 `EMSXSubscriptionEngine` 即基于此订阅订单/路由更新（`backend/api/services/bloomberg/subscriptions.py`）。

---

## 4. 请求/响应服务（Request / Response）

### 4.1 构建与发送
- `service = session.getService("//blp/refdata")`；`request = service.createRequest("ReferenceDataRequest")`。
- `Operation`：`service.getOperation(name)`、`operation.getName()`、`operation.getRequestDefinition()` — 描述请求 schema。
- 填充请求：`Request` 继承 `Element` 的写入方法（`setElement` / `appendElement` 等）。
- 发送：`session.sendRequest(request, correlationId=...)`（同步取响应）或 `sendRequestAsync(request, correlationId=...)`。
- 周期性/模板：`createSnapshotRequestTemplate(...)` + `sendRequestTemplate(...)` — 缓存请求信息，适合高频快照，免去重复解析开销（`RequestTemplate` 随会话失效）。

### 4.2 响应处理
- `Event.REQUEST_STATUS`：请求处理状态（如 `RequestFailure`）。
- `Event.PARTIAL_RESPONSE`：部分响应（大数据量分批）。
- `Event.RESPONSE`：最终响应；**收到 `RESPONSE` 即表示该请求结束**，之后不会再产生相关事件。

---

## 5. 数据解析（Element / Message）

### 5.1 `Message`
- 元数据：`name()`（消息类型 `Name`）、`messageType()`、`correlationId()`、`timeReceived()`（需开启 `recordSubscriptionDataReceiveTimes`）、`topicName()`、`fragmentType()`（`FRAGMENT_NONE/START/INTERMEDIATE/END`，用于分片重拨）。
- 字段遍历：`elementIterator()`（返回 `ElementIterator` 迭代器）、`numElements()`、`hasElement(name)`、`getElement(nameOrIndex)`。
- 便捷取值：`getElementAsFloat(name)` / `...AsString` / `...AsInt32` / `...AsInt64` / `...AsDatetime` / `...AsBool` / `...AsEnumeration` / `...AsName` / `...AsBytes` / `...AsFloat64` / `...AsCharArray`。
- `toPy()`：递归转为原生 Python（`dict`/`list`/`datetime`/标量），便于直接使用。

### 5.2 `Element` — 读取
- 类型判定：`isArray()`、`isComplexType()`、`isSimpleType()`、`isNull()`、`isReadOnly()`、`datatype()`。
- 标量读取：`getValue()`（返回原生类型）、`getValueAs*`（与 Message 同名族）。
- 复合/数组：`getElement(nameOrIndex)`、`numValues()`、`numElements()`、`elementIterator()`、`value()`（数组迭代）。
- 枚举：`getValueAsEnumeration()` 返回 `Constant`。
- `toPy()`：统一转为 Python 对象（数组→`list`，序列/选择→`dict`，标量→原生类型）。

### 5.3 `Element` — 写入（请求与发布）
- `setValue(value)`、`setElement(name, value)`、`setElementNull(name)`。
- 数组追加：`appendValue(value)`、`appendElement()`（用于数组中的复合项）。
- 层级导航：`pushElement(name)` / `popElement()`（进入/退出复合子元素上下文）。
- 请求专用：`setPrefifiedFailed(...)`、`appendMessage(...)`（构造请求主体）。

---

## 6. 事件处理机制（Event Handling）

### 6.1 `Event` 类型（`event.py`）
| 类型 | 触发时机 | 关键 Message |
|---|---|---|
| `SESSION_STATUS` | 会话启停/连接状态 | `SessionStarted`/`SessionTerminated`/`SessionConnectionUp/Down`/`SessionStartupFailure` |
| `SERVICE_STATUS` | 服务打开/注册 | `ServiceOpened`/`ServiceOpenFailure`/`ServiceRegistered`/`ServiceDeregistered` |
| `REQUEST_STATUS` | 请求处理 | `RequestFailure` |
| `RESPONSE` | 请求最终响应（结束标志） | — |
| `PARTIAL_RESPONSE` | 请求分批响应 | — |
| `SUBSCRIPTION_DATA` | 订阅实时数据 | 实际行情/字段 |
| `SUBSCRIPTION_STATUS` | 订阅生命周期 | `SubscriptionStarted`/`SubscriptionFailure`/`SubscriptionTerminated`/`DataLoss` |
| `ADMIN` | 管理事件（含慢消费者） | `SlowConsumerWarning`/`SlowConsumerWarningCleared` |
| `AUTHORIZATION_STATUS` | 授权结果 | `AuthorizationSuccess`/`AuthorizationFailure`/`AuthorizationRevoked` |
| `TOKEN_STATUS` | 令牌生成 | `TokenGenerationSuccess`/`TokenGenerationFailure` |
| `RESOLUTION_STATUS` | 主题解析 | `ResolutionSuccess`/`ResolutionFailure` |
| `TOPIC_STATUS` | 发布主题生命周期 | `TopicCreated`/`TopicActivated`/`TopicSubscribed`/`TopicDeleted`/`TopicRecap` |
| `TIMEOUT` | `nextEvent` 超时 | — |

### 6.2 两种处理模型
- **异步（回调）**：构造 `Session` 时传入 `eventHandler(event, session)`，`EventDispatcher` 在其线程池中按序调用；适合高吞吐、需要即时响应的场景（如 EMSX 实时流）。
- **同步（轮询）**：不传 `eventHandler`，主线程用 `while True: event = session.nextEvent()`；按 `event.eventType()` 分支处理 `event` 内 `Message`。
- 事件内消息通过 `MessageIterator` 遍历（`for msg in event:` 或 `event.__iter__`）。

### 6.3 `Names`（`names.py`）
内置常用消息/状态 `Name` 常量（`SESSION_STARTED`、`SERVICE_OPENED`、`SUBSCRIPTION_TERMINATED`、`AUTHORIZATION_SUCCESS`、`TOPIC_CREATED` 等 50+），避免重复构造字符串 `Name`。

---

## 7. 错误处理（Exceptions）

基础体系（`exception.py`）：`Exception`（基类）下派生：

- `InvalidArgumentException` — 参数非法（如 `eventHandler=None` 却传了 `eventDispatcher`）。
- `InvalidStateException` — 状态非法（如在异步会话上调 `nextEvent`）。
- `InvalidConversionException` — 类型转换失败（如把字符串读成 int、数值超 INT64 范围）。
- `IndexOutOfRangeException` — 下标越界（`getElement(index)` 超界）。
- `NotFoundException` — 字段/常量不存在（`getElement("x")` 不存在）。
- `DuplicateCorrelationIdException` — 关联 ID 重复。
- `UnsupportedOperationException` — 操作不支持（如已废弃的 `ResolutionList.addAttribute`）。
- `FieldNotFoundException` — 字段未找到。
- `UnknownErrorException` / `ValueError` — 其它底层/参数错误。

**统一错误传播模式**：底层 C 调用返回错误码，包装层通过 `_ExceptionUtil.raiseOnError(errCode)` 在 Python 侧抛出对应异常；写入类方法（`setElement`/`publish`/`appendValue` 等）普遍采用此机制，调用方以 `try/except blpapi.exception.Exception` 捕获即可。

---

## 8. 支持的数据类型（DataType）

`DataType`（`datatype.py`）枚举，既是字段类型也是常量类型：

| 类型 | 说明 | Python 映射 |
|---|---|---|
| `BOOL` | 布尔 | `bool` |
| `CHAR` | 字符 | `str` |
| `BYTE` | 字节 | `int` |
| `INT32` | 32 位整数 | `int` |
| `INT64` | 64 位整数 | `int` |
| `FLOAT32` | 单精度 | `float` |
| `FLOAT64` | 双精度 | `float` |
| `STRING` | 字符串 | `str` |
| `BYTES` | 字节序列 | `bytes` |
| `DATE` | 日期 | `datetime.date` |
| `TIME` | 时间 | `datetime.time` |
| `DATETIME` | 日期时间 | `datetime.datetime`（含高精度 picoseconds） |
| `ENUMERATION` | 枚举 | `Constant` |
| `SEQUENCE` | 序列（复合结构） | `Element`/`dict` |
| `CHOICE` | 选择（互斥字段） | `Element`/`dict` |
| `ARRAY` | 数组（以上类型的数组） | `list` |

- **枚举常量**：`Constant` / `ConstantList`（`constant.py`）表示 schema 级枚举值，可 `getValueAs*()`、`getConstant(name)`、`enumeration()`（从 `SchemaTypeDefinition` 取）。
- **日期类型**：`datetime.py` 提供 `FixedOffset(minutes)`（`tzinfo` 实现，可用 `UTC`）、`_DatetimeUtil` 在 Python `datetime` 与 BLPAPI 高精度 datetime（支持 picoseconds 微秒下）之间互转；任意 `datetime.tzinfo` 实现（如 `pytz`）均可用。
- **Name**：`name.py` — 用于高效哈希/比较的字符串键（标识 schema 元素、消息类型、常量名），应"初始化一次，重复使用"以降低查找开销；`Name.findName`/`hasName` 查询全局表。

---

## 9. 认证与身份（Authorization & Identity）

- `Identity`（`identity.py`）：已授权身份，提供 `isAuthorized()`、`getSeatType()`、`getFailedSeatType()`、`toString()`；作为请求/订阅/发布的 `identity` 参数实现权限承载。
- `AuthOptions`（`auth.py`）：认证方式构造器
  - `createWithUserAndApp(user, app, ...)` — 用户名 + 应用凭证。
  - `createWithToken(token, ...)` — 已有令牌。
  - `createWithUserAndToken(user, token, ...)`。
  - `createWithAppAndToken(app, token, ...)`。
  - `createForApp(app)` / `createForConsole()` — 仅应用/控制台。
  - 范围控制：`createWithApplicationMode`/`createWithDirectoryMode` 等（按 app/dir/user 维度）。
- 会话级自动授权：`SessionOptions.setSessionIdentityOptions(authOptions)` 在 `start()` 前自动授权，失败则终止会话。
- 令牌：`Session.generateToken(...)` / `generateTokenAsync(...)`，结果在 `Event.TOKEN_STATUS` 中。

---

## 10. 发布服务（Publishing）

适用自定义数据提供方（如内部行情桥接），与本项目消费端用法互补：

1. **注册**：`providerSession.registerService("//blp/myprovider")` → `Event.SERVICE_STATUS`（ServiceRegistered）。
2. **解析/创建主题**：`TopicList.add(topicString)` → `createTopics(list)` → 收到 `Event.TOPIC_STATUS`（`TopicCreated`/`TopicSubscribed`/`TopicActivated`）；也可 `resolve(resolutionList)` 先解析。
3. **构造事件**：`event = service.createPublishEvent()`（或 `service.createResponseEvent(correlationId)` 用于响应请求）；用 `EventFormatter(event)`：
   - `appendMessage(messageType, topic, sequenceNumber=None)` / `appendResponse(operationName)` / `appendRecapMessage(topic, ...)`。
   - `setElement(name, value)`、`pushElement/popElement`、`appendValue/appendElement`、`setElementNull`。
   - `fromPy(dict)`：用 Python 字典一次性填充（推荐，见 `eventformatter.py` 内完整示例）。
4. **发布**：`providerSession.publish(event)`；`flushPublishedEvents(timeout)` 确保发送完成后再 `stop()`。
5. **响应请求**：作为 provider 还能 `sendResponse(event, isPartialResponse=False)` 回应订阅方请求。
6. **清理**：`deleteTopic(s)` / `terminateSubscriptionsOnTopic(s)` / `deregisterService(serviceName)`。

> 主题广播 vs 交互模型：广播发布者主动 `createTopic*`；交互发布者等待 `TOPIC_SUBSCRIBED` 后再创建。

---

## 11. 元数据与模式（Schema & Name）

- `SchemaStatus`：元素/类型弃用状态（`ACTIVE`/`DEPRECATED`/`INACTIVE`/`PENDING_DEPRECATION`）。
- `SchemaElementDefinition`：字段定义，`name()`、`description()`、`status()`、`typeDefinition()`、`minValues()`/`maxValues()`（`minValues==0` 可选；`maxValues==UNBOUNDED` 无界数组）、`alternateNames()`。
- `SchemaTypeDefinition`：`datatype()`、`isComplexType()`/`isSimpleType()`/`isEnumerationType()`、`numElementDefinitions()`、`getElementDefinition(name/index)`、`elementDefinitions()` 迭代、`enumeration()`（取 `ConstantList`）。
- `Name` / `Names`：见 §8。

---

## 12. 同步 vs 异步接口对照

| 维度 | 同步（Sync） | 异步（Async） |
|---|---|---|
| 会话构造 | `Session(options)`（无 `eventHandler`） | `Session(options, eventHandler, eventDispatcher)` |
| 启动 | `start()`（阻塞到 `SessionStarted`） | `startAsync()`（立即返回，等事件） |
| 事件获取 | `nextEvent(timeout)` / `tryNextEvent()` | `EventHandler(event, session)` 回调 |
| 服务打开 | `openService(uri)` | `openServiceAsync(uri, correlationId)` |
| 请求 | `sendRequest(...)` | `sendRequestAsync(...)` |
| 订阅 | `subscribe(list)` | `subscribeAsync(list)` |
| 适用 | 简单脚本、一次性查询 | 实时流、高吞吐（如 EMSX） |
| 顺序保证 | 单线程天然有序 | `EventDispatcher` 保证单订阅更新/部分响应有序 |
| 停止 | `stop()` | `stop()` / `stopAsync()`（回调内自动转 `stopAsync` 防死锁） |

---

## 13. 使用示例与场景

### 13.1 同步订阅行情（mktdata）
```python
import blpapi

options = blpapi.SessionOptions()
options.setServerHost("localhost")
options.setServerPort(8194)
session = blpapi.Session(options)
if not session.start():
    raise RuntimeError("无法启动会话")

session.openService("//blp/mktdata")
service = session.getService("//blp/mktdata")

subs = blpapi.SubscriptionList()
subs.add("/ticker/IBM US Equity", blpapi.CorrelationId("ibm"),
         blpapi.SubscriptionOptions())
session.subscribe(subs)

while True:
    event = session.nextEvent(500)  # 500ms 超时
    for msg in event:
        print(msg)
    if event.eventType() == blpapi.Event.SESSION_STATUS and \
       msg.messageType() == "SessionTerminated":
        break
```

### 13.2 异步请求参考数据
```python
import blpapi

def handler(event, session):
    for msg in event:
        if event.eventType() == blpapi.Event.RESPONSE:
            print(msg.toPy())  # 终态，请求结束

session = blpapi.Session(blpapi.SessionOptions(), handler)
session.start()
session.openService("//blp/refdata")
service = session.getService("//blp/refdata")
request = service.createRequest("ReferenceDataRequest")
request.getElement("securities").appendValue("AAPL US Equity")
request.getElement("fields").appendValue("PX_LAST")
session.sendRequest(request)
session.run()  # 进入事件循环
```

### 13.3 EMSX 订阅（项目实际用法）
`backend/api/services/bloomberg/subscriptions.py` 中 `EMSXSubscriptionEngine` 用**异步 `Session`** 订阅 `//blp/emapisvc`，在 `EventHandler` 中按 `Event.SUBSCRIPTION_DATA` / `Event.SUBSCRIPTION_STATUS` / `Event.ADMIN` 分流处理订单与路由更新，维护内存缓存并写库（项目实时数据流数据源）。

### 13.4 认证后请求
```python
import blpapi

options = blpapi.SessionOptions()
options.setSessionIdentityOptions(
    blpapi.AuthOptions.createWithUserAndApp("user", "app-name"))
session = blpapi.Session(options)
session.start()  # 启动时自动授权会话身份
```

### 13.5 发布服务（provider）
见 §10 步骤；核心是利用 `EventFormatter.fromPy(dict)` 填充 `service.createPublishEvent()` 生成的 `Event`，再 `providerSession.publish(event)`。

---

## 14. 模块文件索引（源码路径）

```
blpapi/
├── __init__.py             # 公共符号 re-export
├── abstractsession.py      # AbstractSession 基类
├── session.py              # Session（消费者）
├── providersession.py      # ProviderSession + ServiceRegistrationOptions
├── sessionoptions.py       # SessionOptions / TlsOptions / Socks5Config
├── eventdispatcher.py      # EventDispatcher
├── event.py                # Event 类型与容器
├── message.py              # Message
├── element.py              # Element（读/写）
├── service.py              # Service / Operation
├── request.py              # Request
├── subscriptionlist.py     # SubscriptionList
├── correlationid.py         # CorrelationId
├── identity.py             # Identity
├── auth.py                 # AuthOptions
├── topic.py / topiclist.py / resolutionlist.py  # 发布主题与解析
├── eventformatter.py       # EventFormatter（构造发布事件）
├── schema.py               # SchemaTypeDefinition / SchemaElementDefinition / SchemaStatus
├── name.py / names.py      # Name / Names
├── constant.py             # Constant / ConstantList
├── datatype.py             # DataType 枚举
├── datetime.py             # Datetime / FixedOffset / UTC
├── exception.py            # 异常体系与 _ExceptionUtil
├── requesttemplate.py      # RequestTemplate（快照）
├── logging.py              # Logger（日志回调）
├── version.py              # version() / 版本常量
├── internals.py / chandle.py / ctypesutils.py / ffiutils.*.pyd  # C FFI 底层
└── typehints.py / utils.py / debug*.py / diagnosticsutil.py ...  # 工具与类型提示
```

> 说明：`.pyd` 为编译后的 C 扩展，无法阅读；其余 `.py` 均为包装层，本文档结论全部基于对这些 `.py` 源码的逐文件阅读。
