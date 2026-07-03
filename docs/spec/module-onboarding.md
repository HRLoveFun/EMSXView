# 新增模块 / 适配器 / 路由 流程

> AI agent 加新组件时必读
> 配套规范：[ADR-0008](../adr/0008-frontend-module-registry-pattern.md)、[ADR-0002](../adr/0002-platform-data-adapter-pattern.md)
> Last updated: 2026-06-03

---

## A. 新增前端业务模块

适用：新增完整的顶层业务模块（如新增 `RiskView`、`BacktestView`）。

### A.1 创建目录结构

```
frontend/src/modules/<new-module-id>/
├── components/        # 模块内组件
├── hooks/             # 模块内 Hook
├── services/          # API 调用封装
├── stores/            # Zustand 状态存储（如需）
├── types/             # 类型定义
├── views/             # 页面级视图
├── lib/               # 模块内工具
├── data/              # 静态数据 / 配置
├── <NewModule>.tsx    # 模块根组件
└── module.registry.ts # 模块注册入口
```

### A.2 创建 `module.registry.ts`

```typescript
import { moduleRegistry } from '@shared/lib/module-registry';
import type { ModuleDescriptor } from '@shared/lib/module-registry';

const descriptor: ModuleDescriptor = {
  id: '<new-module-id>',         // 唯一标识
  label: '<New Module Name>',    // 标签页显示名
  order: 25,                      // 排序（0-50 内可调）
  isDefault: false,               // 是否默认打开
  loader: () => import('./<NewModule>'),
  // 可选：
  realtimeWsPath: '/ws/<new>',   // 如需实时数据
  showHandoffBadge: true,         // 如需 handoff 提示
};

moduleRegistry.register(descriptor);
```

### A.3 在 Shell 中导入注册入口

修改 `frontend/src/app/App.tsx`：

```typescript
// 顶部 side-effect import
import '../modules/<new-module-id>/module.registry';
```

### A.4 更新规范文档

按顺序同步：

1. `.codebuddy/rules/module-boundary.md` §1.x：添加新模块的边界规则
2. `.codebuddy/rules/project-context.md` 业务模块表：添加新行
3. `docs/spec/anti-patterns.md`：如识别新反模式
4. `docs/spec/module-api-contracts.md`：添加新模块的对外 API

### A.5 验证

```bash
cd frontend
npm run build         # 验证模块能被正确打包
npm run test          # 跑模块测试
npx vitest run src/modules/<new-module-id>/
```

并跑边界测试：

```bash
pytest tests/boundaries/test_module_registry_consistency.py -v
```

### A.6 独立部署（如需要）

修改 `package.json` 的 `build:<module>` 脚本，确保新模块支持 standalone 构建。

---

## B. 新增 platform_data 适配器

适用：跨域需要新的数据访问入口（如新增 `RiskDataAdapter`）。

> **当前代码现状 (2026-06-03)**：`platform_data/adapters.py` 已拆分为
> 子包 `platform_data/adapters/{handoff,market,redis_handoff,tca_bridge}.py`。
> `platform_data/adapters/__init__.py` 做向后兼容 re-export。
> 新适配器应放在子包下。

### B.1 创建子包文件

```
platform_data/adapters/
├── __init__.py           # 维护 re-export 列表
├── handoff.py            # 已有
├── market.py             # 已有
├── redis_handoff.py      # 已有
├── tca_bridge.py         # 已有
└── <new_domain>.py       # 新增
```

### B.2 在 `<new_domain>.py` 定义 Adapter 类

```python
"""<NewDomain> 适配器 — <职责简述>

Owner: <所属子域>
Visible to: <哪些模块可调用>
"""
from __future__ import annotations


class <New>Adapter:
    """<新适配器说明>
    
    公开方法（跨域可见）：<列表>
    私有方法（_ 前缀，跨域禁止）：<列表>
    """
    # 公开方法（跨域可见）
    def public_method(self, ...) -> ...:
        ...
    
    # 私有方法（带 _ 前缀，禁止跨域调用）
    def _internal_helper(self, ...) -> ...:
        ...
```

### B.3 在 `__init__.py` 维护 re-export

```python
# platform_data/adapters/__init__.py
from platform_data.adapters.<new_domain> import (
    <New>Adapter,
)
```

并在 `platform_data/__init__.py` 顶层导出（按需）。

### B.4 更新规范文档

1. `.codebuddy/rules/module-boundary.md` §2.3：添加新适配器到公开/私有分界表
2. `docs/spec/anti-patterns.md` AP-08 配套检测：自动覆盖
3. 新建 ADR（如是新决策）→ `docs/spec/adr/NNNN-<title>.md`

### B.5 编写单元测试

```python
# platform_data/tests/test_<new>_adapter.py
def test_<new>_public_methods():
    adapter = <New>Adapter(...)
    # 测试公开方法
    
def test_<new>_no_underscore_leak():
    """确保跨域调用方无法直接访问私有方法"""
    # ...
```

### B.6 验证

```bash
pytest platform_data/tests/test_<new>_adapter.py -v
pytest tests/boundaries/ -v   # 确保未引入跨域违规
```

---

## C. 新增后端 Router

适用：新增 HTTP/WebSocket 端点组。

### C.1 选择 router 类型

| 类型 | 位置 | 加载方式 |
|---|---|---|
| **Core router** | `backend/api/routers/<name>.py` | `_register_required` |
| **Optional router** | `backend/api/routers/<name>.py` | `_register_optional` |
| **独立服务** | `MarketView/main.py` / `CostView/api/main.py` | 独立部署 |

**判断标准**：
- 涉及 Bloomberg EMSX / 订单执行 → Core router
- TCA / scorecard / 数据库诊断 → Optional router（合并模式加载）
- 独立业务闭环 → 独立服务

### C.2 创建 router 文件

```python
# backend/api/routers/<name>.py
from fastapi import APIRouter, Depends, HTTPException
from ..schemas import ApiResponse
from ..schemas.<name> import <Entity>Schema  # Pydantic v2
from ..deps import get_<service>             # Depends 注入

router = APIRouter(prefix="/<prefix>", tags=["<name>"])

@router.get("/<entity>", response_model=ApiResponse[list[<Entity>Schema]])
async def list_entities(...):
    """列出 <entity>"""
    try:
        result = await service.list(...)
        return ApiResponse(data=result, success=True)
    except Exception as e:
        logger.exception("list <entity> failed")
        return ApiResponse(success=False, error_code="LIST_FAILED", message=str(e))
```

### C.3 在 `main.py` 注册

```python
# Core router
app.include_router(<name>_router)

# Optional router
_register_optional(app, <name>_router, required_modules=["..."])
```

### C.4 编写测试

```python
# backend/api/tests/test_<name>_router.py
from fastapi.testclient import TestClient

def test_list_entities(client: TestClient):
    response = client.get("/api/<prefix>/<entity>")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
```

### C.5 更新规范文档

1. `docs/spec/module-api-contracts.md`：添加新端点到对应模块契约
2. `.codebuddy/rules/module-boundary.md` §4：确认数据访问路径

### C.6 验证

```bash
cd backend/api
pytest tests/test_<name>_router.py -v
pytest tests/boundaries/ -v   # 边界测试
```

---

## D. 跨域新增调用

适用：业务模块 A 需要调用模块 B 当前未暴露的能力。

### D.1 决策流程

```
是否已有 platform_data 适配器方法？
├── 是 → 直接调用 platform_data.<domain>.<method>
└── 否 → 是否应该新增适配器方法？
    ├── 是 → 走流程 B（新增适配器方法）
    └── 否 → 是否走 Handoff 异步交接？
        ├── 是 → 走 ADR-0007 流程
        └── 否 → 重新评估是否真的需要跨域
```

### D.2 禁止模式

❌ 直接 `from CostView.src.* import ...` 跨域
❌ 跨域调用 `platform_data.xxx._internal_*`
❌ 跨域写 `processed_fills.db` / `regime.db`
❌ 在 router 层直接 import 其他 router

详见 [anti-patterns.md §AP-01](../anti-patterns.md)。

### D.3 配套同步

每次跨域调用方式变化：

1. 更新 `.codebuddy/rules/module-boundary.md` 对应章节
2. 若新增适配器方法，更新 §2.3 公开/私有表
3. 若为新决策，建 ADR
4. 添加/更新 `tests/boundaries/` 对应测试

---

## E. 修改现有架构决策

适用：发现当前 ADR 已不适用。

### E.1 不要直接改 ADR

如果决策需要调整：

1. 检查是否有更新决策的 ADR 存在（"Superseded by"）
2. 如果没有，**新建 ADR** 描述新决策，**不要改原 ADR**
3. 在新 ADR 中"引用"原 ADR，在原 ADR 中"被引用"

```markdown
# ADR-0013: 调整 X 决策

> 状态: Accepted
> 替代: [ADR-0001](0001-one-logical-data-domain.md)

## 背景
原 ADR-0001 中 ... 假设已不成立，因为 ...

## 新决策
...
```

### E.2 原 ADR 状态变更

```markdown
# ADR-0001: 一个逻辑数据域，多种存储技术

> 状态: Superseded by [ADR-0013](0013-...)
```

---

## F. 快速检查清单

每次新增/修改跨域组件时：

- [ ] 已在 `.codebuddy/rules/module-boundary.md` 更新对应边界
- [ ] 已在 `docs/spec/anti-patterns.md` 识别新反模式（如有）
- [ ] 已在 `docs/spec/module-api-contracts.md` 记录新 API
- [ ] 已建/更新对应 ADR
- [ ] 已运行 `pytest tests/boundaries/ -v` 且未引入新违规
- [ ] 已运行对应模块的单元/集成测试
