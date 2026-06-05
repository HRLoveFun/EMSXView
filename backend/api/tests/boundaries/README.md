# Boundary Tests

边界测试套件——以"非阻断、可见、可修复"为原则。

## 启动模式

通过 `conftest.py` 顶部 `ENFORCEMENT_MODE` 控制：

| 模式 | 行为 |
|---|---|
| `"record"` | 仅记录违规到 `tests/boundaries/.scan_log.jsonl`，不阻断 |
| `"warn"` | 测试输出黄色告警，仍不阻断 |
| `"block"` | 阻断 CI（仅在 baseline 全部清零后启用） |

**当前默认**：`"record"`（阶段 1 - 1.5：识别期 + 修复期）

## 当前测试

| 测试 | 检测目标 | 对应反模式 |
|---|---|---|
| `test_cross_module_imports.py` | 跨域 deep import + 下划线方法调用 | AP-01, AP-08 |
| `test_router_api_response.py` | router 端点 ApiResponse 包装 | AP-05 |
| `test_db_path_from_config.py` | 数据库路径硬编码 | AP-04 |
| `test_module_registry_consistency.py` | 模块注册与文档一致性 | DOC-DRIFT |

## 执行

```bash
# 全部边界测试
pytest backend/api/tests/boundaries/ -v

# 单个测试
pytest backend/api/tests/boundaries/test_cross_module_imports.py -v

# 查看违规清单（test summary 末尾）
pytest backend/api/tests/boundaries/ -v -s

# 生成 baseline（首次执行）
python backend/api/tests/boundaries/scripts/generate_baseline.py
```

## 违规生命周期

```
阶段 1: 纯记录期
  └─ pytest -v → 显示违规清单（黄色 section），不阻断
  └─ 违规写入 .scan_log.jsonl
  └─ 目标: 收集所有现存违规

阶段 1.5: 批量修复期
  └─ 按严重度（critical → high → medium → low）分批修
  └─ 修复后 baseline -1
  └─ 此阶段仍然不阻断，但禁止新增违规

阶段 2: 严格期（按 git diff 区分新旧）
  └─ 区分 baseline（已知）/ new（本次 PR 引入）
  └─ 仅 new 阻断
```

详见 `docs/spec/memory.md` 与 `.codebuddy/rules/module-boundary.md` 顶部。

## 添加新检测

1. 在 `tests/boundaries/` 创建 `test_<name>.py`
2. 使用 `@pytest.mark.boundary_violation` 标记
3. 调用 `record_violation(config, rule_id, file, message, fix_hint=...)` 记录
4. 用 `pytest.skip(...)` 退出（不抛 assert 失败）
5. 在本 README 添加对应行

## 相关文档

- `.codebuddy/rules/module-boundary.md` — 模块边界契约
- `docs/spec/anti-patterns.md` — 反模式清单
- `docs/spec/module-onboarding.md` — 新增组件流程
