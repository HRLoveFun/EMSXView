# 004-backend-test-stabilization 实施进度跟踪

> 每完成一项，更新状态为 ✅；进行中 ⏳；阻塞 🔴
> 每次 checkpoint 通过后更新对应行

## 总览

| 项目 | 状态 |
|------|------|
| 方案落盘 (plan.md) | ✅ |
| 根因调查（26 项，5 类） | ✅ 本地复现与 CI 一致 |
| C1: test_connection_router 4 项 | ✅ TestClient + app.state 注入（be429f7） |
| C2: logger 3 项 | ✅ re-export logger + _track_api_seq_num 重定向（18a0fc3） |
| C3: connected 9 项 | ✅ 重写注入匹配重构后 handler 接口（ccb99f1） |
| C4: batch fixture 9 项 | ✅ app.state 注入 + mock 契约属性（cd6be3e） |
| C5: psutil 2 项 | ✅ 依赖已声明 + 本地 16 passed |
| CP-1: backend 全量 189 全绿 | ✅ 本地 195 passed，0 failed |
| CI 恢复硬阻断 (boundary.yml) | ✅ 598e172 |
| PR 合并回 main | ⏳ |

## 根因调查记录（2026-08-20）

- **26 项失败全部本地复现**（Windows Python 3.13.5，与 CI Linux 3.12 一致）
- **均为存量测试腐化**：测试文件最后改动 `ec0e06a`（早于 deps 重构 `cfb3c9f`）
- 分类：C1(4) routers.connection 无 get_bloomberg / C2(3) bloomberg_adapter 无 logger / C3(9) connected 无 setter / C4(9) app.state.bloomberg_service 缺失 / C5(2) psutil 缺失

## Checkpoint 记录

### CP-0 单文件修复验证
- [x] C1: test_connection_router 4 passed
- [x] C2: refdata 5 + routing logger 1 passed
- [x] C3: routing 15 passed（含 asyncio/trio 双参数化；修复 Event 整数导致的死循环）
- [x] C4: batch route 9 passed
- [x] C5: pipeline_watchdog 16 passed

### CP-1 backend 全量 189 全绿
- [x] 本地 `pytest tests/ -q --ignore=tests/boundaries` → **195 passed, 0 failed**

### CP-2 CI 硬阻断恢复
- [x] boundary.yml 全量测试去掉 `|| echo WARN`，恢复硬阻断（598e172）
