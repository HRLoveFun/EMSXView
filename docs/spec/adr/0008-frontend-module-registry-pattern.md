# ADR-0008: 前端模块自注册模式

> 状态: Accepted
> 日期: 2026-06-03
> 标签: frontend, architecture

## 背景 (Context)

历史前端是单 SPA，新增/删除业务模块需修改 `App.tsx` / `AppShell.tsx`：
- 硬编码模块列表
- 硬编码 `import('xxx')` 路径
- 硬编码 WS 路径
- 硬编码 handoff 消费者标识

导致：
- 新模块接入需改 Shell
- Shell 与业务模块双向耦合
- 独立部署模块（standalone build）需剥离 Shell 引用

## 决策 (Decision)

采用**模块自注册**模式：

1. **每个模块**导出 `module.registry.ts`：
   ```ts
   import { moduleRegistry } from '@shared/lib/module-registry';
   moduleRegistry.register({ id, label, order, loader, ... });
   ```
2. **Shell** (`frontend/src/app/App.tsx`) 顶部 side-effect import 所有 registry
3. **Shell** 通过 `moduleRegistry.getAll()` 动态渲染 `WorkspaceModuleTabs`
4. **ModuleDescriptor** 字段：
   - `id` / `label` / `order` / `isDefault` — 展示
   - `loader: () => Promise<{ default: Component }>` — 懒加载
   - `realtimeWsPath?` — 声明 WS 端点
   - `showHandoffBadge?` — 声明 handoff 消费方
   - `prefetch?` — hover 预热

## 后果 (Consequences)

### 正面
- 新模块只需在 `App.tsx` 加一行 `import` 注册入口
- Shell 不再硬编码业务模块
- 独立部署时移除对应 `import` 即可
- 标签页顺序、默认模块由 `order`/`isDefault` 声明式定义

### 负面 / 取舍
- 注册时机依赖 side-effect 顺序（已通过 `import` 顶部约定解决）
- 跨模块类型共享需走 `@shared/types`

## 备选方案 (Considered Alternatives)

- 方案 A: 路由式（react-router）
  - 否决原因: 强加路由层级，与"工作区"概念不符
- 方案 B: 配置驱动（json/yaml）
  - 否决原因: 失去类型安全；loader 难以声明式
- 方案 C: 元框架（Module Federation）
  - 否决原因: 部署/构建复杂度与当前规模不匹配

## 相关 ADR

- 引用: [ADR-0007](0007-handoff-exchange-pattern.md)
- 被引用: 无
