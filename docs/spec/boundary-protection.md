# 模块边界防护机制设计（Boundary Protection）

> 状态：**P0/P1/P2 已全部实施**（2026-08-14）
> 关联规范：`.codebuddy/rules/module-boundary.md`、`docs/spec/anti-patterns.md`
> 来源：2026-08-14 全仓库边界风险分析（前端 4 模块 / 后端 3 服务 / 数据管道 5 阶段）

## 1. 背景与问题

全仓库边界分析发现三类越界风险：

- **越界访问**：无认证端点暴露 DB 路径、内部异常泄漏、raw_connection 越权通道
- **越界读写**：handoff 内存字典无上限、Parquet 逐 chunk 覆盖写、归档删除列格式错配
- **参数越界**：保留月数负数无校验、Config 枚举无白名单、schema 字段无边界约束

## 2. 设计原则

1. **纵深防御**：四层防护独立生效，任一层失效不拖垮整体
2. **失败显式化**：所有"静默降级/吞异常/放行"改为显式告警或失败
3. **契约运行时化**：跨模块数据交互必须有运行时 schema 校验，类型断言只是编译期第一道
4. **规则声明式注册**：防护规则由各模块自注册，核心框架零硬编码，天然支持模块增减

## 3. 四层防护架构

```
┌─────────────────────────────────────────────────────────┐
│ L1 输入校验层（Validate）— 一切外部输入的边界入口        │
│   Pydantic 约束补全 · 前端 zod 运行时校验 · Config 校验器│
├─────────────────────────────────────────────────────────┤
│ L2 边界检查层（Guard）— 模块间契约与数据域边界           │
│   BoundaryContractRegistry · handoff schema · 阶段契约  │
│   DB 读写 owner 白名单 · 覆盖写检测 · 删除边界保护       │
├─────────────────────────────────────────────────────────┤
│ L3 访问控制层（Control）— 权限与能力门控                 │
│   认证覆盖 · 敏感信息遮蔽 · 门控开关白名单 · 配额限制    │
├─────────────────────────────────────────────────────────┤
│ L4 异常处理层（Recover）— 统一兜底与降级策略             │
│   异常映射表 · ErrorBoundary · 熔断器修正 · 显式降级     │
└─────────────────────────────────────────────────────────┘
```

### L1 输入校验层（Validate）

| 措施 | 实现方案 |
|------|---------|
| Pydantic 约束补全 | `schemas/orders.py` 的 `symbol/notes/customNote*` 加 `max_length` + pattern；`Route.status/orderType/tif` 改 `Literal` 枚举；`database.date_limit` 加 `ge/le` 约束 |
| 前端 zod 运行时校验 | 新增 `shared/lib/api-schema.ts`：zod 定义 handoff 合约与 API 响应 schema，替换 `handoff-api.ts` 中全部 `as` 断言 |
| Config 参数校验器 | `DataPipeline/config.py` 新增 `_validate_config()`：引擎/后端枚举白名单、保留月数 `ge=0`、日期格式正则，非法值启动即抛异常 |
| 管道日期归一化 | `target_dates`/cutoff 统一归一化为 `YYYYMMDD` 后再比较（H1 根因） |

### L2 边界检查层（Guard）

| 措施 | 实现方案 |
|------|---------|
| BoundaryContractRegistry（核心新增） | `platform_data/contracts/boundary_registry.py`：每个模块声明式注册 `{module_id, can_read, can_write, forbidden_imports, api_auth_required}`。边界测试与审计脚本从注册表生成检测规则 |
| handoff 消息运行时防护 | 载荷 schema 校验（Pydantic 替代 `dict[str, Any]`）、单条消息大小上限、条目上限 + TTL 过期清理（P0 已实施上限） |
| DB 读写 owner 白名单 | 每个 `.db` 文件声明 owner 模块，写入前检查，越界写抛 `BoundaryViolationError` |
| 阶段间数据契约 | 上游行数/日期一致性断言推广到全链路；清洗后空集从静默成功改为 warning + 健康标记 |
| 覆盖写检测 | Parquet `write_batch` 合并写而非覆盖（P0 已实施） |
| 删除边界保护 | 日期列格式感知比较 + retention 校验 + 删除清单快照（P0 已实施） |

### L3 访问控制层（Control）

| 措施 | 实现方案 |
|------|---------|
| 认证覆盖 | database/orders_handoff/realtime WS 补 `verify_token`（P0 已实施）；`OverviewItem.path` 遮蔽为文件名（P0 已实施） |
| 敏感信息遮蔽 | 统一异常映射：内部异常 detail 非 debug 模式替换为分类码；`raw_connection` 移入内部管理端点 |
| 门控统一 | `HANDOFF_BACKEND`/`BDIB_QUERY_ENGINE` 白名单 + 启动校验；`tca_bridge` 重复注册检测 |
| 配额限制 | handoff 内存后端总量上限，超限拒绝写入并返回明确错误码 |

### L4 异常处理层（Recover）

| 措施 | 实现方案 |
|------|---------|
| 异常映射表 | `backend/api/errors.py` 集中定义 `异常类型 → HTTP 状态码 → 安全 detail` 映射，全局 handler 查表转换 |
| ErrorBoundary 全覆盖 | 每个模块懒加载入口各包一层 `ErrorBoundary` |
| 熔断器修正 | 熔断状态跨 run 持久（阈值按阶段累计），Error 阈值 3 才可达成 |
| 显式降级 | `MarketStoreReader.query` 吞异常改为记录 + `source_error` 标记，区分"真无数据"与"查询失败" |
| 管道部分失败显式化 | S5 阶段内异常累计后 `success=False` + 健康清单记录失败 ticker |

## 4. 可扩展性设计（模块动态增减）

核心思想：**规则注册制 + 检测工具规则化生成**，与前端 `moduleRegistry` 模式同构。

1. **契约注册表**（P2，`platform_data/contracts/boundary_registry.py`）：

   ```python
   @dataclass
   class ModuleBoundaryContract:
       module_id: str                      # 如 "costview"
       can_read: tuple[str, ...]           # 如 ("processed_fills", "tca_route_summary")
       can_write: tuple[str, ...]          # 空 tuple 表示只读
       api_auth_required: bool = True      # 该模块 API 是否要求认证
       forbidden_imports: tuple[str, ...]  # 如 ("DataPipeline.src",)
   ```

   新增模块 = 新增一条注册，无需改任何检测代码。

2. **检测工具从注册表生成**：补齐 `audit_cross_imports.py`/`audit_db_paths.py`/`audit_underscore_access.py`（`module-boundary.md` 附录 A 已声明但缺失），检测规则读取注册表而非硬编码 pattern。

3. **执行点闭环**：pre-commit 增加边界审计（快路径）+ CI workflow 跑边界测试与审计脚本。

4. **模块生命周期钩子**：`moduleRegistry.register` 增加 `validate` 钩子；重复注册生产环境 error 级日志；`navigateTo` 增加 `moduleRegistry.has(id)` 校验；多 `realtimeWsPath` 声明冲突检测。

## 5. 风险清单与处置状态

### P0 高危（已修复，2026-08-14）

| # | 风险点 | 修复 |
|---|--------|------|
| H1 | archiver 删除列格式错配致整年误删 | 日期列格式感知比较（ISO 全时间串 vs YYYYMMDD 分策略）+ 删除清单快照 |
| H2 | Parquet 逐 chunk 覆盖写丢数据 | `write_batch` 读-合并-去重-写 |
| H3 | 无认证端点 + DB 路径泄漏 | database/orders_handoff/realtime 补认证；path 遮蔽为文件名 |
| H4 | `_execution_to_cost` 无上限 | 条目上限 500 + 7 天 TTL 惰性清理 |
| H5 | 保留参数负数/0 无校验 | archiver 加 `retention >= 1` 校验（同期 shrink_raw_bdib 已修复并随 2026-08-26 清理归档） |

### P1 机制（已实施，2026-08-14）

| # | 风险点 | 处置 |
|---|--------|------|
| M1 | 输出校验臂生产失效（SchemaRegistry 空注册） | core.py 注册 8 个输出 Schema（RELAXED）；BaseStage 加 `get_output()` 钩子；S2 暴露输出样本（NaN→None）；GuardStage 按短名查 Schema |
| M2 | 前端 handoff 无运行时校验 | 新增 `shared/lib/api-schema.ts`（zod schema + parseApiData/parseApiDataNullable），替换 handoff-api.ts 全部 `as` 断言 |
| M3 | handoff 契约 `dict[str, Any]` 无 schema | `PostTradeHandoffRequest` 字段边界 + strategy_params 64KB 上限（API 层）；适配器 `_bounded_strategy_params()`（双保险） |
| M4 | 订单核心 schema 无边界 | orders/routes/handoff schema 加 max_length/pattern/Literal/ge-le；date_limit Query 约束 |
| M5 | HTTPException detail 泄漏内部异常 | 新增 `backend/api/errors.py`（ErrorCode + error_detail 遮蔽）；全局 5xx handler 遮蔽；broker/debug/route_plans 3 处泄漏点修复；config.py 加 DEBUG 开关 |
| M6 | HANDOFF_BACKEND 无白名单 | `platform_data/config.py` 白名单校验（非法值启动抛错）；`DataPipeline/config.py` 加 `_validate_config()`（引擎/保留月数/策略白名单） |
| M7 | MarketStoreReader 吞异常 | `last_query_error` 标记 + error 日志，区分"真无数据"与"查询失败" |
| M8 | 熔断器 Error 阈值不可达 | `CircuitBreakerRegistry` 失败计数跨 run 持久；OPEN 在 run 结束时转 HALF_OPEN（下个 run 探测） |
| M9 | raw_connection 越权通道 | `ConnectionManager.execute_ddl()` 显式越权通道（ALTER/CREATE 白名单 + 审计日志）；fills.py 改走 execute_ddl；raw_connection 加受限 docstring |
| M10 | S5 部分失败被掩盖 | failed_dates/failed_chunks 健康清单入 summary；全部日期失败时阶段返回 False |

### P2 框架（已实施，2026-08-14）

- **BoundaryContractRegistry**：`platform_data/contracts/boundary_registry.py` — 声明式契约注册（can_read/can_write/forbidden_imports/api_auth_required），7 个内置模块契约，审计脚本从注册表生成检测规则
- **审计脚本补全**：`scripts/audit_cross_imports.py`（AP-01，规则从注册表生成）、`scripts/audit_db_paths.py`（AP-04）、`scripts/audit_underscore_access.py`（AP-08），配合既有 `audit_doc_drift.py` 四项审计全部通过
- **pre-commit 边界审计**：`.githooks/pre-commit` 追加快路径审计（暂存含 .py/.ts/.tsx 时执行，违规阻断提交）
- **CI 接入**：`.github/workflows/boundary.yml` — 审计脚本 + 后端边界/全量测试 + DataPipeline 回归 + 前端 tsc/vitest
- **前端模块生命周期防护**：`navigateTo` 目标校验（未注册 id 拒绝切换）、realtimeWsPath 冲突检测、重复注册生产环境 error 日志、每模块独立 ErrorBoundary

## 6. 成本评估

- 新增代码：P0 约 300-500 行（含测试），P1 约 600-900 行，P2 约 600-900 行
- 零新依赖（zod 已在依赖中、Pydantic 已有、CI 用 GitHub Actions 原生能力）
- 零新进程/服务，运行时开销微秒级（防护点均在写入路径，不影响 TCA 查询 P95 延迟）
- 存储增量接近零（删除保护用清单快照而非全量 .bak，规避历史 57.58 GB .BAK 堆积教训）
