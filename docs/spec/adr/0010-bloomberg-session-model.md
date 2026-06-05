# ADR-0010: Bloomberg 会话模型

> 状态: Accepted
> 日期: 2026-06-03
> 标签: external-integration, backend

## 背景 (Context)

Bloomberg EMSX API 通过 blpapi 提供三类服务流：
1. **订阅流**（Subscription）：订单状态变更推送
2. **请求/响应**（Request/Response）：提交订单、查询历史
3. **市场数据/RefData**：BDIB 行情、参考数据

历史实现把三类流放进同一会话/线程，导致：
- `nextEvent` 轮询竞争（不同类型响应互相阻塞）
- RefData pending 列表管理混乱（曾出现"全局清零"导致关联丢失）
- 字段订阅未持久化，重启需重新订阅

## 决策 (Decision)

Bloomberg 会话**三类流物理分离**：

| 流类型 | 会话/线程 | 管理模块 |
|---|---|---|
| 订阅 | 独立 session + dispatch thread | `services/bloomberg_adapter.py` SubscriptionManager |
| 请求/响应 | 独立 session + coroutine 池 | 同上 RequestResponseManager |
| 市场数据/RefData | 独立 session + dispatcher | 同上 MarketDataManager |

关键规则：
- **订阅字段必须显式进入订阅列表**才会收到（不允许依赖隐式）
- **字段类型必须与解析器类型一致**（不允许 string 解析 number）
- **RefData pending 列表**必须与 correlation id 精确绑定，**禁止全局粗暴清零**
- Bloomberg 启动是 async 后台任务（30-120s BPIPE 初始化），不阻塞应用启动

## 后果 (Consequences)

### 正面
- 三类流互不阻塞
- 关联丢失风险消除
- 字段订阅可持久化

### 负面 / 取舍
- 三套 session 资源占用更高
- 管理复杂度提升

## 备选方案 (Considered Alternatives)

- 方案 A: 单 session 轮询分发
  - 否决原因: 见背景的 `nextEvent` 竞争
- 方案 B: 用 async 库（aioblpapi）
  - 否决原因: 生态不成熟；官方 blpapi 同步模型更稳
- 方案 C: 全部走 RefData
  - 否决原因: 失去实时推送能力

## 相关 ADR

- 引用: 无
- 被引用: 无
