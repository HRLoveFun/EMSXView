# 清理规则集（CL-xx）

> 检测实现：`scripts/cleanup/detectors/`
> 阈值与豁免唯一真相源：`scripts/cleanup/config.py`
> 配套自测：`scripts/cleanup/tests/test_cleanup.py`

**共同前提**：CL-xx 全部是「静态零引用/结构冗余」判定，产出的是**候选**而非结论。
删除前必须过 `safety-protocol.md` 的三轮质询。

---

## 全表

| ID | 名称 | 严重度 | 判定方式 | 实现 |
|---|---|---|---|---|
| CL-01 | 冗余文件（import 图零引用） | high | 从入口白名单 BFS 可达性（复用 OE-01 算法，扫描范围扩至 `data_access/`、`scripts/`） | `dead_files._dead_files` |
| CL-02 | 过时符号（零引用函数/类/常量） | medium / low | 符号名在全库代码语料中仅出现 1 次（仅定义处） | `dead_symbols.detect` |
| CL-03 | 不可达代码 | medium | 终结语句（`return`/`raise`/`continue`/`break`）之后仍有同层语句 | `dead_logic._unreachable` |
| CL-04 | 恒定条件 / 等价分支 | medium / low | `if <常量>`、`while False`、`if` 与 `else` 语句体完全相同 | `dead_logic._const_conditions` |
| CL-05 | 空实现存根 | low | 函数体仅 `pass` / `...` / `return None` | `dead_logic._empty_stubs` |
| CL-06 | 未使用局部变量赋值 | low | 单名目标赋值后在同函数内从未被读取 | `dead_logic._unused_locals` |
| CL-07 | 临时/调试遗留文件 | high | 文件名强特征（`_tmp_` `_debug_` `_verify_` `_old` `_copy` `untitled` …） | `dead_files._temp_leftovers` |
| CL-08 | 空壳模块 | low | 除 docstring/`pass`/`__future__` 外无任何顶层语句 | `dead_files._empty_modules` |
| CL-09 | 注释掉的代码块 | low | 连续注释块（≥4 行）中命中 ≥2 行语句特征 | `dead_logic._commented_code` |
| CL-10 | 前端不可达文件 | medium | 从 4 个构建入口 + 测试装配 BFS 未触达 | `frontend.detect_cleanup` |

**已由 `quality_gate` 覆盖、不重复实现**：`OE-01` 冗余模块、`OE-02` 过度抽象（单实现 ABC / 1:1 传递函数）、
`OE-04` 重复代码块（≥30 行等价块）、`OE-06` 前端未使用导出。全库清理时两套一起跑，取并集。

---

## CL-01 冗余文件

**判定**：文件在 import 有向图中从任何入口不可达。入口 = `main.py`/`__main__.py`/`conftest.py`/`setup.py`、
`scripts/`·`tests/`·`docs/`·`specs/`·`plans/` 目录下的文件，以及 CLI 入口（`cli.py`、`*_cli.py`、`manage.py`）。
动态导入兜底：`importlib.import_module("X")`、`__import__("X")`、`f"pkg.{name}"` 前缀整包视为可达。

**已知误报来源（必须人工核查）**：

- **休眠运维接口**：被 Runbook、`scripts/ops/*.ps1`、桌面快捷方式、CI 配置调用，但代码里无 import
  （ADR-0014 明确保留此类：health_check / daily_update / BDIB 回补族 / FX 回填 / import_excel_fills …）。
- **仓库外消费者**：`EMSXDataPipeline`（数据写入方）可能 import 本仓库的 `data_access/*` 常量或 repository。
- **子进程调用**：`subprocess.run(["python", "xxx.py"])` 不会产生 import 边。

**验证方法**：`rg "<file-stem>" --hidden -g '!*.pyc'` 全仓 + 全配置检索，外加 Runbook/快捷方式/CI 人工查看。

---

## CL-02 过时符号

**判定**：模块级 `def` / `class`（无基类）/ `UPPER_SNAKE` 常量，其名字在**整个代码语料**
（全库 `.py` + `frontend/src/**/*.ts(x)`，排除 `docs/`·`specs/`·`plans/`）中只出现 1 次。

**为什么用「词元计数 == 1」而非 AST 引用图**：

- 字符串形式动态引用（`getattr("foo")`、`{"foo": impl}`、DI 名字、子进程调用）都能被词元计数兜底 → **天然零误报**；
- 代价是漏报（符号在注释/docstring 中出现即不再报告）。
  清理场景的原则是「**漏报可接受、误删不可接受**」，故取此保守方向。

**自动豁免**（见 `config.py`）：

- dunder 名、`DEAD_SYMBOL_EXEMPT_NAMES`（`main`/`lifespan`/`handler`/`create_app` …）；
- 任何装饰器命中的符号 —— 尤其 **Web 框架路由**（`@router.get`、`@app.websocket`、`@bp.route`）与
  pytest fixture / Pydantic validator / Click command（这是历史上最大的误报来源，已由 `names.py` 收敛）；
- 有基类的 `class`（子类/多态场景静态不可证伪）；
- `__init__.py` 内的定义（re-export 语义复杂）；
- `tests/`、`test/` 目录。

**分级**：符号 ≥10 行 → `medium`，否则 `low`。

**验证方法**：IDE 「Find Usages」+ `rg "<name>"` 全仓 + 确认入口文案/前端字符串/API 路由表未引用。

---

## CL-03 不可达代码

**判定**：同一语句体（`body` / `orelse` / `finalbody`）中，终结语句之后仍有语句。

**豁免与注意**：`try/finally` 的 `finally` 体是独立语句体，不会误判；
`if x: return 1` 的 `if` 体只有一条语句，不触发。

**修复**：直接删除。若它是「防御性兜底」（例如 `return` 之后的兜底日志），说明控制流本身有问题，应先调整控制流而不是保留死语句。

---

## CL-04 恒定条件 / 等价分支

**判定**：

- `if <Constant>` / `if <Constant> else` / 三元 `<Constant> ... if` —— 其中一个分支永不执行；
- `while False` / `while 0` —— 循环体永不执行（`while True` **不报**，那是合法的常驻循环）；
- `if` 与 `else` 语句体 AST 等价 —— 条件判定无效果。

**豁免**：`if TYPE_CHECKING:` 是 `Name` 不是 `Constant`，天然不报。

**修复**：删除死分支；需要开关语义时改为配置项/特性标志（显式、可测），而非 `if False`。

---

## CL-05 空实现存根

**判定**：函数体（去掉 docstring 后）仅含 `pass` / `...` / `return None` / `return`。

**自动豁免**：

- dunder 方法；
- `Protocol` / `ABC` / `ABCMeta` / `BaseModel` 子类内的方法（空实现即契约）；
- 装饰器为 `@abstractmethod` / `@overload` / `@property` / `@field_validator` / `@app.on_event`
  / `@click.command` 等；
- docstring 含「占位 / 预留 / TODO / placeholder / not implemented / no-op」——
  **显式声明为占位或兼容 no-op 的函数不算清理对象**；
- 路径含 `stub` / `mock` / `fake` / `fixture`（第三方 API 桩天然由空实现组成，如 `scripts/ci/blpapi_stub/`）。

**例外提示**：`@router.get(...)` 的路由处理器**不豁免**——空实现的路由是真实的未完工接口，应补实现或删除。

---

## CL-06 未使用局部变量赋值

**判定**：函数内单名目标赋值（`Assign` / `AnnAssign`），该名字在同函数内从未被 `Load`。

**自动豁免**：

- `_` 前缀（惯用丢弃名）与 `UNUSED_LOCAL_EXEMPT`（`args`/`kwargs`/`self`/`cls`/`exc`/`err`）；
- 存在 `global` / `nonlocal`，或调用 `locals()`/`globals()`/`eval`/`exec`/`getattr`/`setattr`/`vars` —— 放弃该函数的判定；
- 循环目标、`with ... as`、`except ... as`、海象表达式绑定名（这些不算「赋值后未读」）。

**典型真阳性**：`repo = OrderProjectionRepository(session)` 之后改用 `session.execute(...)`，
`repo` 成为遗留；`stop_event = engine.stop_event` 取出来却没使用。

**修复**：删赋值；若求值有副作用（惰性属性、副作用构造函数），改为裸调用 + 注释说明。

---

## CL-07 临时/调试遗留文件

**判定**：文件名命中强特征（下划线前缀/后缀，避免误伤 `debug_utils.py`、`check_status.py` 这类正常模块）：

```
^_tmp[_-] | ^tmp_ | ^_scratch | ^_debug_* | ^_verify_* | ^_dump_* | ^_probe_* | ^_inspect_*
^_check_ | _old$ | _copy$ | _bak$ | _backup$ | ^untitled | ^new_file | ^temp_
```

**与 `/cleanup-tmp` 命令的分工**：该命令管仓库根 `_tmp/` 与根目录 `_tmp_*` 前缀文件；
本规则补的是**业务树内**的残留（如 `scripts/ops/_tmp_test_blp.py`）。

**修复**：删除，或迁移到 `scripts/ops/` / `docs/` 并去除临时命名（见
`.codebuddy/rules/coding-style.md`「临时代码文件」）。

---

## CL-08 空壳模块

**判定**：非 `__init__.py` 的 `.py` 文件，顶层语句全部为 docstring / `pass` / `__future__` 导入。

**注意**：`__init__.py` 天然豁免（空包标记是合法用法）。

---

## CL-09 注释掉的代码块

**判定**：连续 ≥4 行注释，且其中 ≥2 行匹配语句特征（`def ` / `class ` / `return` / `import ` / `if ` /
`for ` / `while ` / `try:` / `except` / `print(` / `xxx = ...` / 行尾 `{};`）。

**为何需要**：注释掉的代码是「历史备份」的常见伪形态，git 历史才是正确的备份层。
它还会污染检索（`rg` 命中的是死代码），并对后续 AI 代理造成误导。

**豁免**：`scripts/deploy/`（启动器注释密度高且偏说明性）。

**修复**：确认已被替代后删除；保留解释性说明请改写为自然语言注释。

---

## CL-10 前端不可达文件

**判定**：从以下入口 BFS 未触达的 `frontend/src/**/*.ts(x)`：

- `src/main.tsx`（主应用）
- `src/standalone/{execution,costview,marketview}/main.tsx`（三个单模块构建入口）
- `src/test-setup.ts`、所有 `*.test.ts(x)`、所有 `*.d.ts`（前两类由测试运行器直接加载）

说明符解析支持相对路径 `./x`、别名 `@` / `@app` / `@shared` / `@execution` / `@costview` / `@marketview`
（别名映射取自 `quality_gate/config.py::FRONTEND_ALIASES`，与 `vite.config.ts` 保持一致）。

**已知误报来源**：

- `index.html` 直接 `<script src>` 引用的文件；
- 动态字符串拼接的 `import(`；
- 多入口构建配置新增后未同步入口清单。

**验证方法**：`rg "<file-stem>" frontend/ --glob '!*.map'` + 检查 `frontend/*.html` 与
`vite.config*.ts` 的 `rollupOptions.input`。

---

## 人工复核清单（删除前逐条打勾）

- [ ] `rg "<符号/文件名>"` 全仓 + CI/Runbook/快捷方式，无活引用
- [ ] IDE Find Usages 为空
- [ ] 非「休眠运维接口」（Runbook 或运维 `runbook` 提及则保留）
- [ ] 非仓库外消费者（`EMSXDataPipeline`）依赖的读取入口/常量
- [ ] 已有测试覆盖，或已构造特征测试证明行为不变
- [ ] 删除与文档修订在同一次提交
- [ ] 该批次可独立回退（一次一个提交，批间测试全绿）
