---
name: EMSX数据更新频率与缓存优化计划
overview: 优化EMSX系统的数据更新频率管理，实现数据分级更新策略，为低频变化数据（交易员信息、Broker Strategy等）添加本地缓存，减少不必要的API轮询和等待时间
todos:
  - id: create-cache-manager
    content: 创建数据缓存管理器模块，支持内存和LocalStorage两级缓存
    status: completed
  - id: optimize-polling
    content: 优化App.tsx轮询逻辑，分离高频/中频/低频数据更新
    status: completed
    dependencies:
      - create-cache-manager
  - id: cache-trader-info
    content: 实现交易员信息本地缓存，优化为启动时获取
    status: completed
    dependencies:
      - optimize-polling
  - id: cache-broker-strategies
    content: 实现Broker Strategies本地缓存，添加缓存失效策略
    status: completed
    dependencies:
      - create-cache-manager
  - id: optimize-dialog-loading
    content: 优化BrokerStrategyDialog，优先使用缓存减少等待时间
    status: completed
    dependencies:
      - cache-broker-strategies
  - id: add-refresh-ui
    content: 添加手动刷新缓存的UI入口
    status: completed
    dependencies:
      - cache-broker-strategies
---

## 产品概述

优化EMSX交易系统的数据更新频率管理和缓存策略，通过数据分级更新机制减少不必要的API调用，提升系统响应速度和用户体验。

## 核心需求

### 1. 数据分级更新管理

- **高频数据**（1-2秒）：订单数据、路由数据、实时价格
- **中频数据**（30秒）：监控告警计数、连接状态检查
- **低频数据**（日/周级）：交易员信息、Broker Strategies、Strategy参数定义

### 2. 本地缓存优化

- 对变化极少的数据（Broker Strategies、Strategy参数）实现前端本地缓存
- 缓存失效策略：按时间（每日）或手动刷新
- 减少Bloomberg API调用和等待时间

### 3. 现有问题修复

- 交易员信息每2秒轮询 → 优化为每日/启动时获取
- Broker Strategies每次打开对话框都重新请求 → 实现本地缓存
- 缺乏增量更新机制 → 添加时间戳比对

## 变量时效性分析

| 数据类型 | 变化频率 | 当前更新频率 | 建议更新频率 |
| --- | --- | --- | --- |
| 订单数据 (orders) | 高（秒级） | 2秒轮询 | 保持2秒 |
| 路由数据 (routes) | 高（秒级） | 2秒轮询 | 保持2秒 |
| 交易员信息 (traderInfo) | 极低（日级） | 2秒轮询 | 启动时/每日 |
| Broker Strategies | 极低（周/月） | 每次请求 | 本地缓存24小时 |
| Strategy参数定义 | 极低（周/月） | 每次请求 | 本地缓存24小时 |
| 监控告警计数 | 中（依赖orders） | 实时计算 | useMemo优化 |


## 技术栈

### 前端技术栈

- **框架**：React 19 + TypeScript
- **构建工具**：Vite 7.x
- **状态管理**：React Hooks (useState, useCallback, useMemo, useEffect)
- **样式**：TailwindCSS + shadcn/ui
- **存储**：LocalStorage + 内存缓存

### 后端技术栈

- **框架**：FastAPI + Python 3.11+
- **API**：Bloomberg EMSX API (blpapi)

## 技术架构

### 数据分层架构

```mermaid
graph TD
    A[Frontend App] --> B[Data Cache Manager]
    B --> C[Memory Cache]
    B --> D[LocalStorage]
    B --> E[API Service]
    E --> F[FastAPI Backend]
    F --> G[Bloomberg API]
    
    C --> C1[高频: orders, routes]
    C --> C2[中频: connection, alerts]
    D --> D1[低频: broker strategies]
    D --> D2[极低频: trader info]
```

### 更新频率策略

```mermaid
graph LR
    A[App Init] --> B{数据分级}
    B -->|高频| C[2秒轮询]
    B -->|中频| D[30秒轮询]
    B -->|低频| E[缓存优先]
    B -->|极低频| F[启动时获取]
    
    E --> G[检查缓存时间]
    G -->|过期| H[请求新数据]
    G -->|有效| I[使用缓存]
```

## 核心实现方案

### 1. 创建数据缓存管理器

- 统一管理不同频率数据的获取和缓存
- 实现缓存失效检查和刷新逻辑
- 支持手动刷新和自动刷新两种模式

### 2. 优化前端轮询逻辑

- App.tsx中分离高频、中频、低频数据的轮询
- 使用独立的useEffect和定时器管理不同频率
- 页面隐藏时降低轮询频率或暂停

### 3. 实现Broker Strategy缓存

- api.ts中添加缓存层
- route-modify-dialogs.tsx优先使用缓存数据
- 添加缓存时间戳和手动刷新按钮

## 关键代码结构

```typescript
// 数据频率配置
interface DataFrequencyConfig {
  key: string;
  interval: number;      // 轮询间隔ms
  cacheDuration: number; // 缓存有效期ms
  storage: 'memory' | 'localStorage';
}

// 缓存管理器接口
interface CacheManager<T> {
  get(): T | null;
  set(data: T): void;
  isValid(): boolean;
  invalidate(): void;
}
```

## 性能优化要点

1. **减少API调用**：低频数据使用缓存，预计减少30-50%请求
2. **减少等待时间**：Broker Strategy对话框打开时直接使用缓存，无需等待
3. **优化渲染**：使用useMemo减少不必要的重计算
4. **错误降级**：网络错误时优先使用缓存数据

## 实现注意事项

1. **向后兼容**：保持现有API接口不变
2. **错误处理**：缓存失效时自动回退到API请求
3. **内存管理**：限制缓存大小，避免内存泄漏
4. **并发控制**：避免同时发起多个相同请求