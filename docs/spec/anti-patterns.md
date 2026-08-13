# 反模式清单

> AI agent 写代码 / Code Review 必查
> 每个反模式含 ID / 描述 / 检测命令 / 修复方案 / 优先级
> 配套测试：`tests/boundaries/`
> Last updated: 2026-06-29

---

## 严重度分级

| 等级 | 含义 | 修复 SLA |
|---|---|---|
| `critical` | 跨域耦合、违反分层架构 | 1 周内 |
| `high` | 安全/数据正确性风险 | 2 周内 |
| `medium` | 风格、可维护性 | 1 月内 |
| `low` | 命名、注释细节 | 2 月内 |

---

## AP-01 跨域 deep import

**严重度**: critical
**描述**: 前端 import `@costview/*` 或后端 import `CostView.src.*` / `DataPipeline.src.*`
**为什么坏**: 跨域 import 把业务模块的内部细节泄漏到调用方，导致打包膨胀、循环依赖、单元测试无法独立运行
**检测**:
```bash
rg "from ['\"]@costview" frontend/src/modules/execution/
rg "from ['\"]@marketview" frontend/src/modules/costview/
rg "from CostView\.src" backend/api/ platform_data/
rg "from DataPipeline\.src" backend/api/
```
**修复**:
- 前端跨模块 → 改走 `navigateTo` + `useHandoffContracts`
- 后端跨域 → 改走 `platform_data.<domain>.*` 适配器
- 共享类型 → 抽到 `@shared/types` 或 `platform_data/contracts/`
**测试**: `tests/boundaries/test_cross_module_imports.py`
**参考**: [ADR-0002](../adr/0002-platform-data-adapter-pattern.md)、[ADR-0005](../adr/0005-data-pipeline-extraction.md)

---

## AP-02 Router 直接写 SQL

**严重度**: critical
**描述**: FastAPI 路由处理函数中出现 `SELECT` / `INSERT` / `UPDATE` / `DELETE` 字面量
**为什么坏**: 破坏 router → service → repository 三层架构；事务控制困难；测试难以 mock
**检测**:
```bash
rg "(SELECT|INSERT|UPDATE|DELETE)\s+(FROM|INTO)" backend/api/routers/
```
**修复**: 移到 `repositories/<domain>_repo.py`，router 调用 repository 方法
**测试**: `tests/boundaries/test_router_no_sql.py`
**参考**: `.codebuddy/rules/coding-style.md` §状态管理

---

## AP-03 组件直接 fetch/axios

**严重度**: high
**描述**: React 组件中直接调用 `fetch()` / `axios.*`
**为什么坏**: 错误处理不一致；无统一 loading/error 状态；难以添加拦截器（日志/重试/认证）
**检测**:
```bash
rg "(fetch\(|axios\.)" frontend/src/modules/*/components/
```
**修复**: 走模块 `services/` 目录的服务封装
**例外**: 单元测试 (`*.test.tsx`)、`shared/services/realtime.ts` 内部封装
**测试**: `tests/boundaries/test_no_fetch_in_components.py`

---

## AP-04 数据库路径硬编码

**严重度**: critical
**描述**: 代码中出现 `*.db` 路径字符串字面量
**为什么坏**: 改路径需全局 grep；测试/生产环境切换困难；与 `Config` 单一来源原则冲突
**检测**:
```bash
rg "['\"][^'\"]*\.db['\"]" backend/ DataPipeline/ | rg -v "config\.py"
```
**修复**: 通过 `DataPipeline.config.Config.DB_PATHS[...]` 读取
**测试**: `tests/boundaries/test_db_path_from_config.py`
**参考**: [ADR-0012](../adr/0012-config-isolation-rule.md)

---

## AP-05 ApiResponse 包装缺失

**严重度**: high
**描述**: FastAPI 端点返回值未用 `ApiResponse` 包装
**为什么坏**: 前后端响应结构不一致；前端无法统一处理错误码
**检测**:
```bash
rg "@router\.(get|post|put|delete|patch)" backend/api/routers/ -A 5 | rg "return" | rg -v "ApiResponse"
```
**修复**: 改为 `return ApiResponse(data=..., success=True)`
**测试**: `tests/boundaries/test_router_api_response.py`
**参考**: `.codebuddy/rules/coding-style.md` §API 约定

---

## AP-06 注释使用英文

**严重度**: low
**描述**: Python 文件中 `# English comment` 与项目中文约定不符
**为什么坏**: 团队中文环境下阅读障碍
**检测**:
```bash
rg "^#\s+[A-Z][a-z]+" backend/ DataPipeline/ platform_data/ --type py
```
**修复**: 翻译为中文
**例外**: docstring 中的英文术语、第三方 API 引用注释

---

## AP-07 修改其他模块的 Zustand store

**严重度**: critical
**描述**: 业务模块 A 读取/修改业务模块 B 的 Zustand store
**为什么坏**: 跨模块状态耦合；破坏模块独立性；独立部署时丢失状态
**检测**:
```bash
rg "useOrderStreamStore|useRouteStreamStore" frontend/src/modules/costview/ frontend/src/modules/marketview/ frontend/src/modules/databaseview/
```
**修复**: 改走 handoff 契约（`useHandoffContracts`）或 ShellContext
**参考**: [ADR-0007](../adr/0007-handoff-exchange-pattern.md)

---

## AP-08 跨域调用下划线方法

**严重度**: critical
**描述**: 调用 `platform_data.xxx._internal_yyy` 或其他模块的下划线方法
**为什么坏**: 下划线方法是内部实现，跨域调用等于把内部细节钉死到调用方
**检测**:
```bash
rg "platform_data\..*\._" backend/ frontend/src/
rg "\._[a-z_]+\(" frontend/src/ | rg -v "node_modules"
```
**修复**: 仅使用适配器公开 API（无下划线前缀）
**参考**: `.codebuddy/rules/module-boundary.md` §2.3

---

## AP-09 新增 Router 未走 `_register_optional`

**严重度**: high
**描述**: 在 `main.py` 直接 `app.include_router(...)` 而非 `_register_optional`
**为什么坏**: 微服务模式下该 router 仍会被加载，可能引入不必要的依赖（如 Bloomberg session）影响其他模块
**检测**:
```bash
rg "include_router|app\.include" backend/api/main.py | rg -v "_register_optional"
```
**修复**: 改用 `_register_optional(router, ...)` 模式，由 `EMSXVIEW_MERGE_MODULES` 控制
**参考**: [ADR-0009](../adr/0009-blend-of-microservice-and-monolith.md)

---

## AP-10 函数参数/返回值缺类型注解

**严重度**: medium
**描述**: TypeScript 函数缺 `:` 返回类型；Python 函数缺 `->` 返回类型
**为什么坏**: 重构安全网缺失；IDE 提示失效
**检测**:
```bash
# 前端
npx tsc --noEmit
# 后端
pyright backend/ CostView/src/ DataPipeline/ platform_data/
```
**修复**: 添加完整类型注解
**参考**: `.codebuddy/rules/coding-style.md` §类型定义

---

## AP-11 业务代码绕过 ShellContext

**严重度**: medium
**描述**: 业务模块直接调用 `window.location` / 顶层 `fetch` 而非通过 ShellContext
**为什么坏**: 失去 Shell 对认证/WS/Toast 的统一管理
**检测**:
```bash
rg "window\.location\." frontend/src/modules/*/components/ frontend/src/modules/*/views/
```
**修复**: 改用 `useShellContext().navigateTo(...)`

---

## AP-12 WS 连接自行管理

**严重度**: high
**描述**: 业务模块 `new WebSocket(...)` 自行连接
**为什么坏**: Shell 不知道 WS 状态；无法统一重连/可见性恢复
**检测**:
```bash
rg "new WebSocket\(" frontend/src/modules/
```
**修复**: 在 `module.registry.ts` 声明 `realtimeWsPath`，Shell 统一管理
**参考**: [ADR-0008](../adr/0008-frontend-module-registry-pattern.md)

---

## AP-13 Router 缺错误处理

**严重度**: high
**描述**: FastAPI 端点无 try-except 包裹外部调用
**为什么坏**: 异常透传导致 5xx 不友好；日志缺失 context
**检测**:
```bash
rg "@router\.(get|post|put|delete|patch)" backend/api/routers/ -A 10 | rg -v "try:|except"
```
**修复**: 包裹 try-except，返回带 `error_code` 的 `ApiResponse(success=False, ...)`

---

## AP-14 硬编码端口/URL

**严重度**: medium
**描述**: 业务代码中出现 `:3000` / `:8001` / `:8002` 字面量
**为什么坏**: 部署模式切换时需改多处
**检测**:
```bash
rg "localhost:(3000|8001|8002)" backend/ frontend/src/ | rg -v "vite.config|config.py|test"
```
**修复**: 通过 `Config` / `import.meta.env.VITE_API_URL` 读取

---

## AP-15 缺测试覆盖的核心改动

**严重度**: medium
**描述**: 修改 `routers/` / `services/` / `repositories/` 核心逻辑但无对应测试
**为什么坏**: 回归风险累积
**检测**: PR Review 时人工检查 `tests/` 是否同步更新
**修复**: 添加单元测试/集成测试

---

## AP-16 启动器路径硬编码 + 跨宿主语义错位

**严重度**: high
**描述**: 启动脚本（`scripts/deploy/*.vbs` / `*.ps1` / `*.bat`）硬编码"向上 N 层"推算项目根，且 VBS 使用 `WScript.ScriptFullName`（**含文件名**）与 PowerShell 的 `$PSScriptRoot`（**已是目录**）语义不同却复制同一套"向上 N 层"心智模型
**为什么坏**:
- 任何启动脚本被挪到更深/更浅的目录都会**静默坏掉**，无任何保护
- VBS 路径算错时不会立即报错，而是让子进程跑一个不存在的 `.ps1`、然后等 120s 超时——症状像"环境问题"实为代码 bug，极易误导
- 诊断日志目录 `logs\` 与错误页 `startup-error.html` 都派生自算错的项目根，于是扫到**完全无关的运维日志**（如 `cleanup_b4_*.log`、`observation_*.log`）冒充启动日志，进一步误导排查方向
- "重启电脑后启动失败但 `restart-all.bat` 又能救回"是典型症状——因为只有桌面快捷方式走 VBS 一条路径，手动修复命令走的是 `service-manager.ps1` 正确路径

**检测**:
```bash
# 1. 硬编码"向上 N 层"模式
rg "GetParentFolderName.*GetParentFolderName" scripts/deploy/  # VBS 嵌套调用
rg "Split-Path -Parent.*Split-Path -Parent" scripts/deploy/    # PowerShell 嵌套调用
rg "Join-Path \$PSScriptRoot ['""]\.\." scripts/               # 相对深度硬编码

# 2. VBS 中出现业务逻辑（应已收敛到 ps1）
rg "Sub |Function " scripts/deploy/*.vbs  # 旧 VBS 残留的业务子程序

# 3. 启动器无项目根自检
rg "Assert-ProjectRootValid|Find-EmsxviewRoot" scripts/deploy/  # 应至少出现一次
```

**修复**:
1. **单一信息源**：项目根放 `.emsxview-root` marker 文件，启动器通过 `Find-EmsxviewRoot` 向上查找 marker（参考 `.specify/scripts/powershell/common.ps1` 的 `Find-SpecifyRoot` 同型模式）
2. **fail-fast 自检**：算出项目根后立即断言 `frontend\package.json`、`backend\api\main.py`、`.emsxview-root` 存在，错路径毫秒级 throw，禁止 120s 超时
3. **跨宿主陷阱消除**：VBS 削到 < 30 行 thin wrapper，只负责"隐藏窗口 + 调起 PowerShell"，**VBS 内零业务逻辑、零路径深度计算**
4. **marker 兜底**：marker 丢失时回退到 `$PSScriptRoot\..\..` 仍经自检，保持向后兼容

**参考**:
- `scripts/deploy/launch-emsxview.ps1`（Find-EmsxviewRoot + Assert-ProjectRootValid）
- `scripts/deploy/launch-emsxview.vbs`（thin wrapper 范式）
- 事故根因：2026-06-29 VBS `GetParentFolderName` 少算一层导致 `EMSXVIEW_ROOT` 落到 `scripts\`，每次重启都 120s 超时且诊断页显示 B4 数据库清理日志

---

## 附录：一键扫描

```bash
# 全部 AP 检测
bash scripts/scan_anti_patterns.sh

# 单项检测
bash scripts/scan_anti_patterns.sh AP-01
bash scripts/scan_anti_patterns.sh AP-04
```

或逐条执行对应 `rg` 命令。
