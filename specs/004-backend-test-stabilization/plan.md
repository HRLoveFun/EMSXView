# 实施计划: backend 全量测试存量失败修复

**Branch**: `004-backend-test-stabilization` | **Date**: 2026-08-20 | **状态**: 已立项

**背景**: 2026-08-20 CI（`boundary-protection`）接入后，backend 全量测试 189 项中 26 项失败（163 passed）。经调查，26 项全部为本 PR（003-tca-core-benchmarks）之前的**存量测试腐化**——测试文件最后一次修改 `ec0e06a`，早于 `deps.py` 重构 `cfb3c9f`（服务注入改为 `app.state` 模式），测试未同步。

**门控规范**: `docs/spec/plan-design-principles.md`（G0 数据零受损 / G1 三性齐备 / G2 全程防漂移 / G3 充分且必要）

---

## Summary

修复 backend 全量测试 26 个存量失败，使 CI `后端测试 (FastAPI + boundaries)` job 由"降级为 WARN"恢复为**硬阻断**（真正防御边界回归）。所有修复均限**测试文件**与必要的**测试支撑代码**，不触碰生产业务逻辑；若个别失败根因确为生产代码缺陷（如 `connected` 只读属性确实需要 setter），则按最小化原则评估并单独记录。

## 根因分类（已本地复现，与 CI 一致）

| # | 类别 | 数量 | 文件 | 根因 |
|---|------|:---:|------|------|
| C1 | `routers.connection` 无 `get_bloomberg` | 4 | `test_connection_router.py` | 测试 `monkeypatch.setattr(connection, "get_bloomberg", ...)` 引用不存在函数；路由已改用 `Depends(get_bloomberg_service)` |
| C2 | `bloomberg_adapter.logger` 不存在 | 3 | `test_bloomberg_adapter_refdata.py` ×2、`test_bloomberg_adapter_routing.py` ×1 | 测试引用顶层模块 `logger`，实际定义于子包 `services/bloomberg/adapter.py:39` |
| C3 | `connected` property 无 setter | 9 | `test_bloomberg_adapter_routing.py` | 测试 `service.connected = True`，属性只读（委托 `_conn.connected`） |
| C4 | `app.state.bloomberg_service` 缺失 | 9 | `test_batch_route_endpoints.py` | fixture 只设 `deps._bloomberg_service`，未注入 `app.state`；`get_bloomberg_service` 读取 `request.app.state` |
| C5 | `psutil` 缺失 | 2 | `test_pipeline_watchdog.py` | 依赖缺失（CI 已补；本计划确保显式声明） |

## 统一技术原则（G0 数据零受损 / G2 防漂移）

| # | 原则 | 落地 |
|---|------|------|
| R1 | 测试行为不变 | 只改"如何把 fake/mock 注入"，不改断言预期与业务语义 |
| R2 | 生产代码最小改动 | 优先在测试侧修复；仅当生产属性缺失 setter 是**真实缺陷**时才改生产代码（C3 专项评估） |
| R3 | 本地可复现 | 每个修复在 Windows 本地 `python -m pytest <file>` 验证通过，再推 CI |
| R4 | CI 恢复硬阻断 | 全部修复后，`boundary.yml` backend 全量测试去掉 `|| echo WARN`，恢复 exit code 阻断 |
| R5 | 不回退 | 不删除测试、不 `xfail`、不 `skip` 除非证明该测试测的是已废弃行为 |

## 修复方案

### C1: `test_connection_router.py`（4 项）— 改为 TestClient + app.state 注入

**理论依据**: 路由已迁移至 FastAPI `Depends(get_bloomberg_service)`（读取 `request.app.state`），直接 `asyncio.run(health_check())` 无法传入依赖。应通过 `TestClient` 触发真实依赖解析。

**技术方案**:
- 新增 fixture 构造 `FastAPI` app，`app.state.bloomberg_service = _FakeBloomberg(...)`，`app.include_router(connection.router)`，`monkeypatch.setenv("BYPASS_AUTH","true")`
- `health_check`/`get_startup_status` 测试改为 `client.get("/api/health")` / `client.get("/api/startup-status")`
- `monkeypatch.setattr(connection.settings, "ENABLE_DB_PERSISTENCE", ...)` / `check_database_connection` 保留

**检验方法**: `python -m pytest tests/test_connection_router.py -q` → 0 failed。

### C2: `bloomberg_adapter.logger`（3 项）— 指向真实 logger

**理论依据**: `services/bloomberg_adapter.py` 是薄包装 re-export，`logger` 定义在 `services/bloomberg/adapter.py`。

**技术方案**:
- 测试改为 `from services.bloomberg.adapter import logger as adapter_logger` 或 `monkeypatch.setattr(bloomberg_adapter, "logger", <fake>)`（若 re-export 缺失，则确认是否应在 `bloomberg_adapter.py` 补 `from services.bloomberg.adapter import logger`——属测试支撑最小改动）

**检验方法**: 两文件对应用例全绿。

### C3: `connected` 无 setter（9 项）— 专项评估

**理论依据**: `connected` 是 `BloombergEMSXService.connected` 只读 property，委托 `self._conn.connected`（`BloombergConnectionManager`）。测试意图是"假装已连接"以测下游逻辑。有两种合法路径：
1. 测试改为 `service._conn.connected = True`（若 `_conn.connected` 有 setter 或直接赋值）
2. 若 `_conn.connected` 也是只读且无法赋值，则生产代码**应**为测试可注入性提供 setter 或改测试用 mock `_conn`

**技术方案**: 先检查 `BloombergConnectionManager.connected` 定义；若可赋值则用路径 1（零生产改动）；否则在 `BloombergEMSXService` 增加 `@connected.setter`（最小生产改动，向后兼容，仅委托 `_conn.connected`）。

**检验方法**: `python -m pytest tests/test_bloomberg_adapter_routing.py -q` → 0 failed。

### C4: `app.state.bloomberg_service`（9 项）— 更新 fixture

**理论依据**: `app_with_mock_bloomberg` fixture 注入 `deps._bloomberg_service` 是 deps 重构前模式；重构后 `get_bloomberg_service` 读 `request.app.state.bloomberg_service`。

**技术方案**:
- fixture 在 `app.state.bloomberg_service = bloomberg`（保留 `deps._bloomberg_service = bloomberg` 兼容旧依赖，或清理）
- 确认 `deps.get_bloomberg_service` 是否仍引用 `_bloomberg_service`（若已删除全局，则只设 app.state）

**检验方法**: `python -m pytest tests/test_batch_route_endpoints.py -q` → 0 failed。

### C5: `psutil` 依赖（2 项）— 依赖声明

**技术方案**: CI 已装；另确认 `backend/api/requirements.txt` 或 CI 显式含 `psutil`，并本地验证 `python -m pytest tests/test_pipeline_watchdog.py -q`。

**检验方法**: 对应用例全绿。

## 全流程防漂移检查（G2）

| CP | 触发点 | 检查 | 通过标准 |
|----|--------|------|---------|
| CP-0 | 每个 C 类修复后 | 单文件 pytest | 该文件 0 failed，其余通过数不减少 |
| CP-1 | 全部修复后 | backend 全量 `pytest tests/ -q --ignore=tests/boundaries` | 189 全绿（163 passed + 26 修复） |
| CP-2 | CI 恢复硬阻断后 | workflow run | `后端测试` job SUCCESS（去掉 `|| echo WARN`） |
| CP-3 | 回归 | 边界测试 `pytest tests/boundaries/ -q` | 不因测试改动引入边界违规 |

## 改动-需求双向矩阵（G3）

| 改动 | 根因 | 需求 |
|------|------|------|
| C1 4 项 TestClient 改造 | deps 重构后测试未同步 | 恢复 CI 硬阻断 |
| C2 3 项 logger 指向 | 模块拆分后 re-export 缺失 | 恢复 CI 硬阻断 |
| C3 9 项 connected 注入 | 属性只读 + 测试未同步 | 恢复 CI 硬阻断 |
| C4 9 项 fixture app.state | deps 重构后注入契约变化 | 恢复 CI 硬阻断 |
| C5 2 项 psutil | 依赖未声明 | 恢复 CI 硬阻断 |
| boundary.yml 恢复硬阻断 | 存量失败清零 | G2 防漂移 |

**范围外**: 不新增测试；不重构 deps 注入模式；不改业务逻辑（除非 C3 证明 `connected` setter 是真实生产需求）。
