# 自迭代复盘日志（Iteration Log）

每次清理/优化任务收尾时**追加**一条记录；高频误报与遗漏同步滚动进下面的「高频段」。
下一次任务开始时读最近 3 条 + 高频段，作为本轮校准输入
（优先复核历史遗漏模式、放低历史误报模式的出现阈值）。

---

## 记录格式

```markdown
### YYYY-MM-DD · <任务/范围>

- **扫描规模**：N 文件 / M 行 Python；CL 命中 n / PF 命中 n
- **实际删除**：n 文件 / n 符号 / n 行（分 B1-B5 批）
- **优化落地**：n 处（含前后对比数字）
- **误报**（工具报出但经核实不成立）：
  - `RULE` 现象 → 根因 → 已采取的豁免/收敛措施
- **遗漏**（事后才暴露的死代码/性能问题）：
  - 机制缺失点 → 建议补充的规则或阈值
- **分级偏差**：定级过高/过低的条目及原因
- **规则/阈值变更**：本次对 `config.py` 与规则集的修改
```

---

## 高频误报段（滚动更新）

| 规则 | 误报模式 | 收敛措施 |
|---|---|---|
| CL-02 | FastAPI 路由处理器（`@router.get` 装饰器按名字注册，无 import 边） | `names.py::decorator_tokens` 提取装饰器属性链；`ROUTE_DECORATOR_METHODS` / `ROUTE_DECORATOR_TOKENS` 豁免 |
| CL-02 | pytest fixture / Pydantic validator / Click command | 同上（`DEAD_SYMBOL_EXEMPT_DECORATORS`） |
| CL-02 | 有基类的类（多态/子类场景静态不可证伪） | `node.bases` 非空即豁免 |
| CL-01 | 休眠运维接口（Runbook / 快捷方式 / PS1 调用，无 import） | 无法自动判定 → 人工核查后加 `DEAD_FILE_EXEMPT` 或 `--suppress` |
| CL-01 | CLI 入口（`*_cli.py`） | `CLI_ENTRY_NAMES` / `CLI_ENTRY_SUFFIXES` 视为入口 |
| CL-05 | 第三方 API 桩包（`scripts/ci/blpapi_stub/` 天然由空实现组成） | `EMPTY_STUB_EXEMPT_PATH_PARTS`（路径含 stub/mock/fake/fixture） |
| CL-05 | 显式声明为 deprecated no-op 的兼容方法 | docstring 关键词 `no-op` / `noop` 豁免 |
| CL-06 | 局部变量被 `locals()` / `eval` 间接读取 | 函数含动态访问（`locals`/`globals`/`eval`/`exec`/`getattr`/`setattr`/`vars`）即整体放弃判定 |
| PF-02 | 2 层嵌套循环（小集合遍历极常见） | 2 层降为 `low`，≥3 层才 `medium` |
| PF-04 | 实现注册表（`_x_registry[key] = impl`，条目数由实现数量决定，天然有界） | 名称含 `registry`/`impl(s)`/`factor(y\|ies)`/`singleton` 豁免；常量键写入不计增长 |
| PF-01 | `dict.get()` 被误判为 HTTP 调用 | HTTP 类调用需接收者名命中 `client/session/requests/httpx/http/api/url/resp/endpoint` |
| PF-08 | `X.Provider` 点号组件名 / 跨行 props 不匹配 | 正则改为 `<((?:\w+\.)*\w*Provider)\b[^>]*?value=\{\{`，并对全文 `finditer` 后回算行号 |
| PF-03 | f-string 被按「单个 Constant 片段」判定，`LIMIT ? OFFSET ?` 写在另一片段的分页查询被判无界 | 改为对**整条 SQL** 评估：f-string 由各片段拼接、表达式占位为 `?`；参与 `+` 拼接的字面量片段同样标记为拼装并降级 |
| PF-03 | 模块/函数 docstring 中的示例 SQL 被当作可执行查询 | 预收集 docstring 常量节点 id 并跳过 |
| PF-03 | `CREATE OR REPLACE VIEW ... AS SELECT *` 被当作数据加载（DuckDB/Parquet 视图是惰性的） | `RE_LAZY_DDL` 命中即不判 |
| PF-03 | 注册表/标签类小表（`order_label`、`*_registry`、2 千余行）全读被判「结果集不可控」 | 表名命中 `RE_BOUNDED_TABLE_NAME` 降级为 low |
| PF-03 | 有 WHERE 约束的 `SELECT *` 与真无界混为一谈 | 分级：无 WHERE/LIMIT 且非小表 → medium；其余（列未裁剪 / 受约束 / 拼装待确认）→ low |
| OE-06 | 跨行 import 子句漏匹配（`_RE_IMPORT` 带 `^` 锚点按行扫描，`import {\n a,\n} from 'x'` 整条丢失）→ 真实消费者未登记，导出被判「无消费者」 | 增 `_RE_ML_IMPORT` / `_RE_ML_EXPORT_LIST` 全文补扫（`_scan_multiline_clauses`），仅处理含换行的子句 |
| OE-06 | 别名导入 `import { X as Y }` 记为消费 `Y`（绑定名）→ 源名 `X` 被判无消费者 | 拆 `_parse_source_names`（取 `as` 前）/ `_parse_binding_names`（取 `as` 后）；import 与 re-export 的**来源侧**一律用源名 |
| OE-06 | 导出仅在本文件内使用 → 不是死代码，原 fix_hint「删除该导出及其实现」会删掉活符号 | fix_hint 改为「去掉多余 export 关键字……切勿删除实现」；同文件使用型待单列子类（见遗漏候选段） |
| PF-01 | `for r in cursor.fetchall():` 的迭代表达式只求值一次，却被 whole-loop walk 算作循环内 IO | `_io_calls_in_executed`：只统计 body/orelse，`While.test` 保留（条件每轮求值） |
| 消费者统计（CL-02 同源口径） | 包顶层 `__init__.py` re-export 的 **DI 工厂**（`get_tca_query_service` / `register_tca_service_impl`）静态零消费者 → 会被反复提为删除候选；但它们是 `module-api-contracts.md` §平台适配器入口 与 `data-domain.md` §使用示例 逐字写明的**文档化公开入口** | 按「**零调用方的公开 API 依然是 API**」一律豁免；已在 `module-api-contracts.md` 该节写明 2026-09-16 复核结论，避免后续会话重复提议 |
| CL-xx（能力边界） | 对 `__init__.py` 的 re-export 面**零命中**（检测器视为有意兼容面）→ 「兼容 re-export 面与契约规则冲突」这类冗余**不会被工具报出** | 只能靠人工「契约一致性」审查（本次即由 `module-api-contracts.md:304` 的导入规则反查出 27 个违规 re-export）；建议后续为包入口 re-export 增设「与文档化导入规则一致性」提示项 |

---

## 遗漏候选段（已知能力边界，未实现）

| 能力缺口 | 现状 | 替代手段 |
|---|---|---|
| 类方法的零引用判定 | **已内置为 `CL-12`**（2026-09-15，见下）；CL-02 仍只判模块级符号 | 内置检测器；vulture 退化为可选交叉核对 |
| 跨文件重复代码块 | 由 `quality_gate` OE-04（AST 归一化整函数匹配）覆盖 | 直接跑 `quality_gate --ruleset oe` |
| 未使用的 npm / pip 依赖 | 未实现 | knip（JS）/ deptry（Python） |
| 前端打包体积归因 | 未实现 | `vite-bundle-visualizer` |
| 运行时热点测量 | 刻意不做（静态工具不得冒充 profiler） | py-spy / cProfile / tracemalloc / React Profiler |
| 数据驱动的索引缺失 | 只做 SQL 文本静态提示 | `EXPLAIN QUERY PLAN`（唯一权威） |
| `quality_gate` 扫描范围漂移 | `quality_gate/config.py::PYTHON_SCAN_ROOTS` 仍含已迁出的 `DataPipeline`，且**缺 `data_access`** → OE-01/02/04/05 对 `data_access/` 整层（本仓库发现数最多的模块，66 项）零覆盖 | 建议同步扫描根；因会新增大量基线项，需单独评估后执行（不在本次清理授权内） |
| `parse_module` 静默失败 | 解析失败（如 BOM / 语法错误）与「无 import 边」不可区分，图类规则会静默误报 | 已修 BOM 根因；后续可让检测器把「解析失败文件」单独列为提示项 |
| 行号型指纹的产生抖动 | 位置级规则（`nested@{line}` / `comment@{line}` / `unreachable@{line}`）在无关行增删后会换 fingerprint，被记为「新增 + 清偿」各若干 | 属设计取舍（位置即身份）；批量编辑工具文件时会出现个位数抖动，可忽略；如需消除可改为内容片段哈希 |
| 级联失效 | 删除一个文件会让「仅供其使用」的下游符号新变为零引用（本次 `exchange_tz.batch_convert_ny_to_local` 即如此） | 删除批次完成后**必须复扫一次**再定下一批，勿按首轮清单一次性删完 |
| OE-06 同文件使用型 | 「导出无跨文件消费者」包含两类：真死代码 vs 仅本文件使用的多余 `export`（含 shadcn/ui 的 `export { A, B }` 约定与模块内部类型面），后者删除即破坏编译 | 待实现：把「同文件仍有引用」单列子类并降级为提示；`_is_exempt` 目前不排除 `__tests__/`，测试内的 `export function measure` 会混入清单 |
| OE-06「同文件使用」计数含 `export` 行 | 本文件出现次数（`own > 1`）把**声明处的 `export` 语句本身**计入 → `export function X(){}` 这种「仅靠导出维持被使用」的符号被判成 SAME_FILE_ONLY（实测 `PopoverAnchor`：裁剪导出列表后 `tsc --noUnusedLocals` 立即报 TS6133） | 判定时应**扣除导出语句行**再计数；前端收敛批次以 `tsc -b` 兜底（`noUnusedLocals` 会把这类伪存活暴露为编译错误） |
| 部分扫描污染趋势库 | `cleanup --ruleset cl|pf` 仍写 `scans` 记录（n_findings=0），`last_full_scan()` 取到虚假 0 项基准 → 报告趋势表与「环比上次全量」失真 | **已修**（2026-09-14）：`_is_full_coverage(mode, ruleset)` 统一 `save_scan` 与 `_maintain_baseline` 口径；分析型单规则集扫描不再入库 |
| 检测器修复 ≠ 真实清偿 | 修复误报后同批 fingerprint 从基线消失，被记为 `fixed`，会虚高「存量清偿率」 | 统计与复盘时须扣除「修复导致的消失」数量；本轮为 71（OE-06 跨行）+ 1（别名）+ 3（PF-01 头部）= 75 项 |
| 子串遮蔽（假阴性） | 外部审计脚本用 `sub.name in text`（子串）判定跨文件存活：`get_distinct_dates` 被 `get_distinct_dates_in_range` 遮蔽、`_fill_bdib_conn` 被 `tca_query_builder.py` 的同名**模块级函数**遮蔽 → 真死方法被判存活 | 判定存活必须用**词边界正则**（`(?<![\w.])name(?![\w])`）并区分「同名不同实体」；删除后须复扫以捕获级联 |
| 类方法零引用判定 | `CL-02` 只判模块级符号，类方法需外部工具 | **已内置为 `CL-12`**（2026-09-15 收尾批次，见下）；补丁另一处同类缺陷：`_fill_bdib_conn` 被同名**模块级函数**遮蔽 → 引入「同名实体区分」 |

---

## 记录

### 2026-09-10 · 框架建成与首次全库验证（范围：全仓，373 文件）

- **扫描规模**：373 文件 / 32,513 行 Python / 2.5s（full，含前端入口 BFS）
- **首轮结果**：CL 命中 90 → 收敛后 44；PF 命中 222 → 220（其中 PF-06 热点候选 15）
- **误报**（首轮报出、经核实不成立，已收敛，详见「高频误报段」）：
  - CL-02 报出 40+ 个 FastAPI 路由处理器（`@router.get/…`）→ 根因是装饰器只取了属性名、漏了
    `router` 接收者与 Call 形态；已新增 `names.py` 统一提取装饰器属性链，并引入路由装饰器豁免。
  - CL-05 报出 `scripts/ci/blpapi_stub/` 的第三方 API 桩方法与 1 个显式 deprecated no-op →
    分别以路径特征与 docstring 关键词豁免。
  - PF-04 报出 `_config_registry` / `_tca_service_registry` 等实现注册表 → 以「注册表命名 + 常量键」
    双重豁免（保留 `_parent_store` 这类真实的动态键累积容器）。
  - PF-08 正则漏配 `ThemeContext.Provider`（点号组件名）→ 已修正并补跨行匹配。
- **首轮确认真阳性（未误报）**：`backend/api/service_provider.py:180` 遗留 `repo = …` 未使用、
  `bloomberg/enrichment.py:117` `stop_event` 未使用、`scripts/hooks/session-summary.py:32`
  `input_data` 未使用、`data_access/processing/fill_cleaner.py` + `schema/columns.py` 整条链路不可达、
  `scripts/ops/_tmp_test_blp.py` 临时件残留。
- **误报根因（跨框架，已修共享基础设施）**：CL-01 把 `backend/api/services/broker_storage_service.py`
  报为不可达，但 `backend/api/main.py:135` 明明导入了它。追查到根因是
  **UTF-8 BOM**：`backend/api/main.py`、`backend/api/auth.py`、`data_access/processing/fill_cleaner.py`
  三个文件带 BOM，而 `quality_gate.ast_utils.read_text_safe` 用 `encoding="utf-8"` 读入后首字符为
  `\ufeff`，`ast.parse` 直接抛 SyntaxError → `parse_module` 返回 None → **该文件的所有 import 边丢失**，
  于是只被它导入的下游模块被误判为不可达。修复：`read_text_safe` 改用 `utf-8-sig`
  （BOM 剥离；无 BOM 时行为完全一致），并补 `test_read_text_safe_strips_utf8_bom`。
  该缺陷同时影响 `quality_gate` 的全部 AST 检测器（OE-01/02/04/05），属既有隐患。
  **教训**：文件级 import 图类规则的误报，优先怀疑「解析是否成功」而非「图算法是否正确」；
  检测器应考虑把 `parse_module` 返回 None 的文件单独列为「解析失败」提示，而不是静默当作无边。
- **分级偏差**：初版把 CL-02 的长符号全判 `medium`，实测存量偏多；
  已保留「≥10 行判 medium」但确认其作为**批次排序信号**而非阻断依据。
- **规则/阈值变更**：
  - 新增 `ROUTE_DECORATOR_METHODS` / `ROUTE_DECORATOR_TOKENS` / `CLI_ENTRY_NAMES` /
    `CLI_ENTRY_SUFFIXES` / `EMPTY_STUB_EXEMPT_PATH_PARTS` / `RE_BOUNDED_CONTAINER_NAME`；
  - `EMPTY_STUB_PLACEHOLDER_HINTS` 增补 `no-op` / `noop`；
  - PF-02 改为 2 层 `low` / ≥3 层 `medium`；
  - PF-06（热点 Top-N）改为**仅 full 模式输出** —— staged 模式只看得见少数文件，
    排序失去意义且会把 full 扫描不产出的 fingerprint 带进基线，污染「存量清偿」统计；
  - `_EVICT_TEMPLATE` 移除「重置赋值」这一伪有界证据（`CACHE = {}` 不代表有界）。
- **未执行项**：knip / vulture / py-spy / EXPLAIN QUERY PLAN 均未运行（本轮为机制验证，非优化执行）；
  报告已声明「外部工具未执行」，未虚构结果。

### 2026-09-10 · 首轮执行（B1~B3，授权后）

- **用户决策**：① `platform_data/contracts/data_access.py` 保留并加入 `DEAD_FILE_EXEMPT`；
  ② 跨仓库依赖在管道仓库确认；③ 授权执行 B1~B3；④ `quality_gate` 扫描根漂移**另行评估**（本轮不动）。
- **跨仓库确认（决定性否定）**：在管道仓库全量检索 `from data_access|import data_access|
  data_access.storage|common|processing` → **0 命中**；其 README 自述「本仓库为独立数据管道，
  **不依赖 EMSXView 代码树**」，跨仓库交互仅通过环境变量 `EMSXVIEW_DATA_DIR` 与可选的
  `EMSXVIEW_REPO_DIR` 测试钩子（未设置即 skip）。且管道仓库拥有自己的同名实现
  （`DataPipeline/storage/schema/columns.py`、`DataPipeline/processing/fill_cleaner.py`、
  `DataPipeline/common/exchange_tz.py`、`DataPipeline/storage/connection.py`）。
  → **EMSXView 侧 `data_access/` 的零引用符号可安全删除**，此前「待确认」项解除。
- **实际删除（B1~B3，共 5 项 + 5 处符号/常量）**：
  - B1：`scripts/ops/_tmp_test_blp.py`（命名即临时，全仓零引用）
  - B2：`data_access/processing/fill_cleaner.py` + `data_access/storage/schema/columns.py`
    （不可达簇；`columns.py` 仅被 `fill_cleaner.py` 引用）
  - B3：`quality_gate/ast_utils.py::iter_imports`、`ast_utils.py::_NESTABLE`、
    `scoring.py::severity_breakdown`（含随之不再使用的 `Severity` 导入）、
    `config.py::AP_ENFORCEMENT` / `OE_ENFORCEMENT`
- **保留判定（偏离原计划 1 项，已记录理由）**：`platform_data/contracts/data_access.py` —— 见用户决策①。
- **同步文档（与删除同一批改动）**：`README.md`（目录树 schema/processing 注释）、
  `docs/spec/data-domain.md`（删除 `DataPipeline/processing/fill_cleaner.py` 对应物映射行、
  修正 `processing/` 指针）、`data_access/processing/__init__.py` 与
  `data_access/storage/schema/__init__.py`（docstring 去除对已删模块的引用）、
  `docs/spec/quality-gate.md`（基线演进表：门禁语义当前硬编码于 `scoring.gate_verdict`，
  不再声称 `OE_ENFORCEMENT` 开关有效）。
  **未改动历史记录**：`docs/spec/adr/0005`、`docs/archive/**`、`specs/**` 中的历史提及。
- **验证**：`compileall` 全仓 exit 0；`data_access` 全部子包导入 smoke 通过；
  `pytest scripts/quality_gate/tests scripts/cleanup/tests` → **56 passed**；
  四个 `audit_*.py` 全绿；复扫 `cleanup` → **0 新增 / 241 存量**。
- **量化收益**：清理项 **44 → 22（−50%）**，CL-02 **31 → 13**，CL-01 **3 → 0**，CL-07 **1 → 0**；
  文件数 373 → 370；存量清偿 26 项。性能项 220 → 219（随删除减少 1 处嵌套循环）。
- **级联发现（删除后复扫才暴露，已进入下一轮清单）**：`data_access/common/exchange_tz.py::batch_convert_ny_to_local`
  （77 行）因 `fill_cleaner.py` 被删而失去唯一消费者，现为零引用；
  同文件 `get_local_time_str` / `get_local_date_str` 亦零引用（合计 3 个函数 / 111 行）。
- **剩余待办**：B4（CL-02 余 13 项：`tca_utils.py` 5 个工具函数、`exchange_tz.py` 3 个、
  `connection.py::backup_database` / `ALL_DATABASE_NAMES`、`query_cli.py::format_output` 等）、
  B5（CL-06 9 处未使用赋值）、PF 实测（PF-03 的 `market_store.py`/`raw_fills.py` 与 PF-06 Top3 优先）。
  跨仓库确认已完成，`data_access/` 侧 B4 项不再需要二次确认。

### 2026-09-10 · 剩余待办执行（B4 / B5 / PF 实测）

- **B4（CL-02 余 13 项，已提交 `eb3d012`，−287 行）**：删除 `side_sign` /
  `derive_local_exchange_time` / `floor_time_to_10s` / `time_key` / `to_optional_float` /
  `format_output`（51 行）/ `_MINOR_UNIT_CCYS` / `_css_id` / `get_local_time_str` /
  `get_local_date_str` / `batch_convert_ny_to_local`（117 行）/ `backup_database` / `ALL_DATABASE_NAMES`；
  级联清除 `derive_local_exchange_datetime` 与随之失效的 3 个导入；
  移除已无消费者的 `tabulate` 依赖。`backup_database` 属写/管理能力，删除同时强化 ADR-0016 只读边界。
- **B5（CL-06 9 处，已提交 `4cdadc4`）**：`service_provider` 2 处 `repo = …`、
  `enrichment` 4 处（`stop_event`/`old_rate`/`old`/`sample`）、`tca_report_html` 2 处
  （`title`/`mid`，`title` 失效连带移除仅服务于它的 `is_all` 形参与调用点实参）、
  `session-summary.py` 的 `input_data`（保留读 stdin 的协议副作用，改为裸调用 + 注释）。
- **⚠️ 本轮一次真实失误（由测试捕获，须记入教训）**：在 `tca_utils.py` 清理导入时，
  用 `git grep` 判断 `math` / `defaultdict` 是否被使用，**输出被 `Select-Object -First 30` 截断**，
  我据此误删了两个仍在使用的 import；CostView 测试立即以 7 个 `NameError` 失败暴露。
  **教训与固化做法**：判断「符号是否仍被使用」**禁止依赖可能被截断的文本 grep**，
  改用 AST 判定（`Names`/`Attributes` 全量收集后比对导入名）。本批随后用临时脚本
  `_tmp/_tmp_unused_imports.py` 对 9 个被改文件做了逐文件 AST 校验，仅发现 1 处我引入的
  `datetime`（已修）与 3 处既有未使用导入（`service_provider.py` 的 `asyncio`/`Optional`、
  `enrichment.py` 的 `Set`，不在本批范围，留待「无用 import」规则覆盖）。
- **PF 实测（1）：PF-03 规则自身缺陷修正** —— medium 候选 **21 → 1**。
  对 21 条候选提取真实 SQL 后发现：12 条含 WHERE 约束、1 条在 docstring 里、1 条是惰性视图定义、
  6 条是 f-string 片段误判、3 条是注册表小表；**唯一真阳性**是
  `data_access/storage/repositories/fills.py:107 SELECT * FROM processed_fills`（无 WHERE/LIMIT）。
  另 21→1 的降幅说明：**「静态候选」经实测后大部分不是缺陷 —— 这正是要求实测的原因**。
- **PF 实测（2）：只读 `EXPLAIN QUERY PLAN` 取证**（数据根 `D:\db`，只读连接）：

  | 表 | 规模（max(rowid)） | 查询 | 计划 |
  |---|---|---|---|
  | `processed_fills` | **74,713,724** | `SELECT *`（无 WHERE） | `SCAN` |
  | `processed_fills` | 同 | `order_as_of_date = ?` | `SEARCH USING INDEX idx_proc_date` |
  | `processed_fills` | 同 | 日期范围 + ORDER BY | `SEARCH ... + USE TEMP B-TREE FOR RIGHT PART OF ORDER BY` |
  | `raw_fills` | **14,338,234** | `source_date = ?` | `SEARCH USING INDEX idx_raw_source_date` |
  | `raw_fills` | 同 | `substr(order_as_of_date,1,10) = ?` | **`SCAN`（索引失效）** |
  | `equ_ticker_registry` | 2,423 | `SELECT * ... ORDER BY` | index scan（小表，合理） |

- **PF 实测（3）：新增规则 PF-09**「WHERE 列被函数包裹导致索引失效（sargability）」——
  由上述第 5 行实测证据驱动；真实仓库命中 **1 条、零误报**（即该行本身）。
  这是静态规则做不到、只有「实测 → 反哺规则」闭环才能产出的一类问题。
- **PF 实测（4）：系统级发现** —— 全部业务库**无 `sqlite_stat1`**（从未 `ANALYZE`），
  计划器缺统计信息；建议在数据维护侧（独立仓库 EMSXDataPipeline）例行流程加入 `ANALYZE`。
- **未执行（需授权与场景）**：`fills.py:107` 的语义化改写、`raw_fills.py:60` 的等价改写
  （须 before/after 实测对比）、`PF-06` 热点函数的真实 profiler 采样（需可复现业务场景与日期区间）。
- **验证**：`pytest` backend 192 / CostView 103 / 门禁单测 63 全绿；四个 `audit_*.py` 全绿；
  `compileall` exit 0；cleanup 复扫 **清理项 0**。

#### 补充取证（并入 main 后，为两项待办做决策准备）

- **`raw_fills.order_as_of_date` 的格式契约（权威来源：管道仓库）**：
  `DataPipeline/processing/fill_cleaner.py:113` 记为 **YYYYMMDD**（管道分区键）；
  `DataPipeline/processing/tca_route_metrics.py:200` 明确「两表格式不一致：raw_fills 为 YYYY-MM-DD、
  processed_fills 为 YYYYMMDD」；`analysis/regime/fill_regime_tagger.py:14` 称 processed_fills 为
  **legacy 'YYYYMMDD'**。本仓库只读抽样（LIMIT 3）得到 8 位 `'20260305'`。
  → 结论：**`raw_fills.order_as_of_date` 历史上格式混杂**，这解释了 `get_fills_for_date()`
  为何采用三级 fallback（等值 → substr → source_date）；**L2 不是死分支，而是针对历史
  ISO 格式数据的兼容分支，不可删除**。
- **`raw_fills` 索引清单与改写可行性（只读实测）**：
  `idx_raw_source_date(source_date)` / `idx_raw_order_date(order_as_of_date)` / `idx_raw_ticker(Ticker)` 均存在。
  | 写法 | 计划 |
  |---|---|
  | `order_as_of_date = '2025-09-15'`（L1） | `SEARCH USING INDEX idx_raw_order_date` |
  | `substr(order_as_of_date, 1, 10) = '2025-09-15'`（L2 现状） | **`SCAN`** |
  | `order_as_of_date >= '2025-09-15' AND < '2025-09-16'`（L2 改写） | `SEARCH USING INDEX idx_raw_order_date` |
  → L2 可**等价改写**为范围条件（对 8 位、ISO 日期、ISO 日期时间、NULL 与短值逐一推演均等价），
  预期由 1433 万行 `SCAN` 降为索引 `SEARCH`；**待授权后实施并做 before/after 计时对比**。
- **`fills.py:102 get_all_processed_fills()` 的真实性质（静态确证）**：
  docstring 明写 "Return all processed fills"（全表读取为**有意设计**），且**全仓零调用方**
  → 它是**死方法**而非「性能缺陷」；正确处置是**删除**（或明确保留为导出接口并豁免），
  而**不是**加 `LIMIT`/`WHERE`（那会违背其文档化契约）。
  该案例同时暴露能力边界：`CL-02` 不判类方法，故此类「类方法死代码」只能靠 vulture 或人工发现。

### 2026-09-10 · 两项待办执行（授权后，用户指定基线日期 20260831）

- **`raw_fills.py::get_fills_for_date()` 的 L2 分支改写**（授权 + 用户给定日期 + 同意真实计时）：
  - **数据形态实测（1 次全扫）**：`order_as_of_date` 三种格式并存 —— `len=8` 7,648,102 行 /
    `len=10` 2,263,969 行 / `len=19` 4,126,419 行（共 14,338,090）。
    → 证实 L2 **不是死分支**（639 万行历史 ISO 数据依赖它），此前的"疑死分支"判断被数据推翻。
  - **改写方案对比（真实投影 `SELECT *`，同语义返回 0 行）**：
    | 写法 | 计划 | 耗时 |
    |---|---|---|
    | ① 现状 `substr(order_as_of_date,1,10) = ?` | `SCAN raw_fills` | **51.937s** |
    | ② 范围 `>= ? AND < ?`（次日上界） | `SEARCH ... USING INDEX idx_raw_order_date` | **0.000s** |
    | ③ `LIKE ?`（绑定参数） | `SCAN raw_fills` | 4.164s |
    | ④ `LIKE 'literal%'` | `SCAN raw_fills` | 4.125s |
    → **`LIKE` 在 SQLite 下未被优化为索引范围**，必须用范围条件（这一步靠实测才避免选错方案）。
  - **等价性**：按指定日期对全表 14,338,090 行逐行比对两谓词判定，`mismatch = 0`；
    对 ISO 样例日期 `2025-12-22` 亦 `mismatch = 0`。
  - **端到端复测**：`get_fills_for_date('20251222')`（L1 为空 → 实走 L2）返回 **54,888 行 / 0.411s**；
    改写前同一调用需 `SCAN` 全表（实测 ~52s）+ 取回 5.4 万行。
  - 结论：**~52s → 0.411s**（同语义、同结果集），代码路径已实测验证。
- **`fills.py::get_all_processed_fills()` 处置 = 删除**（接口意图调查：`protocols.py` 未声明该方法、
  全仓零消费者、管道仓库仅有其自有同名副本、文档/Runbook 未提及 → 证据不支持"有意外部导出接口"）。
  该删除同时消除 PF-03 的唯一 medium（`SELECT * FROM processed_fills` 对 7470 万行表全扫）。
- **规则归零**：`PF-03` medium **1 → 0**；`PF-09` **1 → 0**（改写后 substr 形态消失）。
- **⚠️ 本轮第二次自身失误（自查捕获）**：删除 `get_all_processed_fills` 时，我把 `new_str`
  误写成下一方法名（`def get_processed_fills_for_date_range(`），导致紧随其后的
  `def get_distinct_dates_in_range(` 被拼接成一行非法签名。
  代码本身仍能通过 `py_compile` 之外的多数检查（`compileall` 在我修复后才跑），
  但 **AST 方法清单校验**立刻暴露了异常。**固化做法**：任何删除/重命名编辑后，**立即**执行
  `compileall` **且** 用 AST 打印类方法清单做结构比对；`new_str` 表示"净删除"时**不得**夹带锚点行。
- **本轮统计**：两次失误（截断 grep 误删 import、锚点写错损坏签名）均在提交前被
  「测试」与「结构校验」捕获 —— 印证 skill 的两条纪律（**批间必测**、**改动后必验**）不是形式主义。
- **未执行（下轮）**：PF-06 profiler 实测（路径 A 在线 py-spy 采样 / 路径 B 离线 cProfile 基准，
  需服务运行或日期区间）、前端渲染热点录制（PF-07/PF-08，需 React DevTools Profiler）。

### 2026-09-11 · mktdata 修复生效验证（重启后）

**重启方式**：项目受支持流程 `service-manager.ps1 restart -Environment dev`（后端 + 前端同时重启，
后端新 PID 38352，Bloomberg connected、INIT_PAINT 32 订单加载正常）。

| 指标 | 重启前（修复前，旧 PID 59972） | 重启后（新 PID 38352） |
|---|---|---|
| py-spy 20s 采样 | 380 样本，100% 落在 mktdata 线程 3 个 helper | **2 样本，全部在 blpapi `nextEvent`（C 层事件等待）** |
| 10s CPU（GetProcessTimes） | 1.44s = **14.4%** of one core | 0.02s = **0.2%**（**−98.6%**） |
| 线程状态 | mktdata 线程 `active+gil`，栈在 `_maybe_query_round_lot_sizes` | 全部 **idle**，mktdata 线程在 `nextEvent` 等待 |
| 热循环日志 | `[MKTDATA CHECK]`/`[ROUND_LOT]` INFO 每轮输出 | 已删除（本批） |
| `TRACE_*` / `Duplicate` | 5,380+5,380 / 577 | 重启后日志 **0 条** |
| 后端日志体积 | 前次运行 2.1 MB / 2 天 | 1.4 KB（含启动输出），稳态近零 |
| 功能 | Bloomberg connected | Bloomberg connected、INIT_PAINT 32 订单加载正常 |

**结论**：四项修复全部生效 —— 空闲态 CPU **14.4% → 0.2%（−98.6%）**，日志噪声归零，
行情订阅与推送功能正常。

**可复现验证命令**（`_tmp/` 下的脚本因 Safe-Delete 钩子被拦截未能保留，需时可重建）：

```
py-spy dump --pid <backend_pid>
py-spy record --pid <backend_pid> -d 20 --format speedscope -o _tmp/after.json --nonblocking
python _tmp/_tmp_parse_profile.py _tmp/after.json
python _tmp/_tmp_cpu_delta.py <backend_pid>
```

**方法论**：验证必须用与「发现时」完全相同的口径（同工具、同窗口、同指标），
否则 14.4% → 0.2% 这种结论无法成立；绝对 CPU%（GetProcessTimes 差分）比采样占比更有说服力。

### 2026-09-10 · 前端实测（方案 A / C / D）

- **A（Vitest + React.Profiler）**：新增 `settings-nav.test.tsx`（3 用例）——commit 计数、
  导航回调正确性、渲染耗时冒烟预算（<50ms）。**先决更正**：检索发现前端**已有** 17 个测试文件 /
  136 个测试全绿（此前误判「无前端测试」，根因是检索 glob 未按预期递归）。
- **C（无头浏览器 + MutationObserver / PerformanceObserver，Playwright 驱动 dev server 5173）**：
  切换 Execution / Cost View / Market View / Settings 视图，累计 **317 次 DOM mutation / 75 个
  节点变更 / 0 个长任务（>50ms）** → `PF-07`/`PF-08` 命中在当前数据规模（5 订单 / 11 行表格）
  下**不构成实测性能问题**，属规模增长后才显现的潜在项。
- **D（体积归因）**：`npm run build` 9.68s（2643 modules），分块表（raw / gzip）：
  vendor-charts 265/60.5KB、ExecutionModule 259/65.9KB、vendor-misc 190/65.4KB、
  vendor-react 189/59.2KB、module-costview 150/36.2KB、vendor-radix 106/29.8KB、
  vendor-ui 92/26.1KB、module-marketview 34/9.2KB、index 28/9.4KB、css 61/11.4KB、
  vendor-icons 16/5.5KB（总计约 1.39MB / gzip 378KB）。
  **构建警告**：`Circular chunk: vendor-misc -> vendor-react -> vendor-misc` ——
  `manualChunks` 造成的循环 chunk，是体积/初始化顺序维度的**真实问题**（待单独处理）。
- **教训**：「存在性」结论（有没有测试/文件/引用）**必须用第二种方式复核**——
  本次 `search_content` 的 glob 未递归，导致误判「前端无测试」并写进了测试文件注释（已更正）。

### 2026-09-11 · quality_gate 扫描根漂移评估与修复

**评估方法**：不改配置，用 quality_gate 自身检测器在三种扫描根组合下**模拟实测**
（每组合 2.5–3.4s），再按增量决定是否落地。

**漂移实况**：`PYTHON_SCAN_ROOTS` 含不存在的 `DataPipeline`（010 迁出）且缺 `data_access`
（13 文件 / 1,848 行，本仓库唯一数据入口）；`dead_modules._RESOLVE_ROOTS` 同源残留。

**影响实测（关键更正）**：此前估计「会新增约 66 项基线」**是错的** —— 那是
`scripts/cleanup`（CL+PF）的发现数，与 quality_gate 的 **OE** 规则集不同（OE=过度工程/
复杂度/死模块）。实测：

| 场景 | 判定对象 | OE 合计 | 增量 |
|---|---|---|---|
| 现状（含不存在的 DataPipeline） | 125 文件 | 80 | — |
| +data_access | 138 文件 | 82 | **+2** |
| +data_access +scripts | 182 文件 | 95 | +15（scripts 自指 13） |

**增量的 2 项均为真实问题，处置不同**：

| 项 | 处置 | 理由 |
|---|---|---|
| OE-02 `connection.py:400 database_exists`（1:1 传递） | **suppressed 并注明** | 它同时是 `ConnectionManagerProtocol`（`platform_data/contracts/protocols.py:55`）声明的 **API 边界方法**，唯一调用方 `platform_data/regime_query.py:40` —— 内联会破坏契约；按检测器自身指引走豁免 |
| OE-05 `market_store.py:117 get_market_context`（CC 24） | **拆分修复** | 无契约约束；拆为 `get_market_context`(CC 7) + `_empty_context_row` / `_route_interval_bounds`(12) / `_fill_close_prices`(7) / `_fill_bar_completeness`(2) / `_expected_bars`(2)，行为保持 |

**实施**：
1. `quality_gate/config.py::PYTHON_SCAN_ROOTS`：删 `DataPipeline`、补 `data_access`
2. `dead_modules._RESOLVE_ROOTS`：移除 `DataPipeline`、补 `data_access`（同源残留）
3. `market_store.get_market_context` 拆分（CC 24 → 7，子函数 ≤12）
4. `database_exists` suppressed（指纹 `cc43346eaaa8…`，注明理由）
5. **未纳入 `scripts`**：+13 项全是 quality_gate/cleanup 自身的自指发现（scripts 清理视角由
   `scripts/cleanup` 承担）—— 自指扫描只会制造噪声并推高基线

**验证**：`pytest backend/CostView/quality_gate/cleanup` **358 passed / 1 skipped**；
quality_gate 自测 21 passed；复扫 **OE 新增 0 / 存量 254**（OE-05 清偿 1、OE-02 豁免 1）；
cleanup 复扫清理项 0。**

**教训（第二次同类失误）**：「新增 N 项」的估计**必须实测而非口算** —— 我把两套规则集
（cleanup 的 CL+PF 与 quality_gate 的 OE）的发现数混为一谈，高估了 33 倍。
跨规则集的影响评估必须先跑模拟再下结论。

### 2026-09-10 · PF-06 实测（路径 B 离线基准 + 路径 A 在线 py-spy 采样）

**环境事实（先探活再动手，避免重复起服务）**：后端 (3000, PID 59972) 与 Vite dev server
(5173, PID 54784) **已在运行**；8001/8002/Redis 未起；`redis` 包缺失。
`py-spy 0.4.2` 安装于 `D:\anaconda3\Scripts\py-spy.exe`。

**路径 B —— 离线 cProfile（TCA 服务路径，日期区间 20260830-20260831；仅 20260831 有数据）**

| 工作负载 | wall | 时间去向 |
|---|---|---|
| `build_tca_report(include_time_series=True)` | 0.175s | sqlite `fetchall` 0.065 / `execute` 0.062 / `get_time_series` 0.100 |
| `build_tca_report(include_time_series=False)` | 0.034s | 仅 `tca_route_summary` 查询 |
| `build_order_report(limit=200)` | 0.000s | 该日期无 order 聚合数据 |
| `build_scorecard(broker_strategy)` | 0.203s | `execute` ×20 = 0.105 / `_row_to_route_summary` ×2000 = 0.034 |

→ **结论：TCA 请求路径无 CPU 热点**，耗时全部是 SQLite IO 且总量 < 0.25s。
`PF-06` 中 `tca_utils.aggregate_cohorts`(720)、`anomaly_query.query_anomaly_routes`(1260)
在此负载下不构成瓶颈。**这正说明「热度分只用于排序，必须实测」**。

**路径 A —— 在线 py-spy 采样（针对运行中后端）**

- `py-spy dump`：**唯一持有 GIL 的活跃线程是 `mktdata-subscription`**，栈落在
  `_maybe_query_round_lot_sizes (enrichment.py:610)`；MainThread 处于 asyncio 空转（无请求）。
- 空闲态 20s 采样（377 样本，叶帧自耗时）：

  | 占比 | 函数 | 位置 |
  |---|---|---|
  | 28.4% | `_update_mktdata_subscriptions` | `enrichment.py:308` |
  | 26.3% | `_maybe_query_round_lot_sizes` | `:610` |
  | 11.7% + 6.9% | `_maybe_query_ticker_currencies` | `:547` / `:548` |
  | 5.8% | `_update_mktdata_subscriptions` | `:320` |
  | 2.7% / 1.1% | `_maybe_query_round_lot_sizes` | `:609` / `:611` |

**根因（代码确证）**：`_mktdata_subscription_loop`（`enrichment.py:154`）的 `while` 循环
**没有任何 sleep / 节流**，唯一节奏来自 `sess.nextEvent(2000)` —— 当会话有事件积压时可退化为满速自旋；
且每轮**重复构造 3 个 O(#orders) 集合**（`:306`、`:544`、`:606`），并在热循环内保留调试日志
（`:310-317` 的硬编码 `[MKTDATA CHECK]`、`:612-628` 的 `[ROUND_LOT]` INFO）。

**日志侧交叉佐证（独立证据链）**

| 日志 | 规模 | 主要消息 |
|---|---|---|
| `logs/api/emsx_api.log` | 3.2 MB | `WARNING TRACE_GET_ORDERS` **5,380**；`WARNING TRACE_WRITEBACK` **5,380**；`[MKTDATA PERMFAIL REFDATA]` **~5,958**；`Failed to send ... Duplicate` **577** |
| `logs/service/backend-20260901-175225.log` | **2000 MB（2 GB / 2 天）** | 尾部主体为反复的 **Python traceback 帧** → 历史错误循环 |
| `logs/service/backend-20260907-214050.log` | 2.1 MB（当前运行） | `GET /api/startup-status` 2,394；`/api/exchanges/handoff/candidates` 1,272；`/api/broker-recommendations` 1,272（前端轮询） |

**由实测产出、待授权修复的问题清单**

1. 后台循环**无节流**（空闲即吃 CPU）→ 加 `stop_event.wait(0.2~0.5s)` 或改事件驱动；
2. 每轮重建 O(#orders) 集合 → 增量缓存（orders 变更时才重建）；
3. `refdata` 请求**重复发送被拒**（`Duplicate` 577 次）→ `_*_pending` / `_*_queried_tickers`
   守卫存在竞态或覆盖不全（与热点函数完全对应）；
4. **调试日志遗留**：`TRACE_*` 前缀以 `WARNING` 级别刷 1 万余次；热循环内 `[MKTDATA CHECK]` / `[ROUND_LOT]` INFO；
5. 历史 2 GB traceback 日志所示错误循环是否已消除，需查当前日志的异常频率。

> 「复现一段使用」在本例中**不需要人工操作**：服务自身的前端轮询
> （`startup-status` / `handoff/candidates` / `broker-recommendations`）已构成真实负载，
> 而 `py-spy dump` + 日志频率足以定位根因 —— **先做零负载采样，再决定是否造负载**。

**能力缺口（新增）**：CL 规则**不检查日志语句**，故「级别错用 / TRACE 遗留 / 热循环内 INFO」
这类问题只能靠人工或外部工具发现 —— 建议新增 `CL-11 调试日志遗留`（热循环内 INFO/WARNING、
`TRACE_`/`DEBUG_` 前缀但非 DEBUG 级别、硬编码 ticker 的 check 分支）。

### 2026-09-14 · 全库全面清理复盘（范围：全仓；**只报告**，未删除任何生产代码）

- **模式与规模**：全库 / 强度=只报告；376 文件 / 33,396 行 Python；CL 命中 **0** / PF 命中 214（含 PF-06 15）
- **清理侧结论**：`CL-xx = 0`（既有存量已在 B1~B5 批次清完）。检测器自测 42 passed，
  排除「检测器失效导致的假阴性」——**本轮无删除对象**。
- **并集侧（quality_gate OE）**：OE 存量 **259 → 187**（−72）。本轮真正的产出不是新清单，
  而是**修复了 3 类会产生错误删除建议的检测器缺陷**（详见「高频误报段」）。

- **误报（工具报出、经核实不成立）**：
  - `OE-06` 跨行 import：`_RE_IMPORT` 带 `^` 锚点按行匹配，`import {\n a,\n} from 'x'`
    整条漏匹配 → 消费者未登记。`use-handoff-contracts.tsx` / `handoff-api.ts` / costview 的
    `lib/*` 与 `types.ts` 全部因此入列：**158 项中 71 项**（45%）为误报，且 fix_hint 指示
    「删除该导出及其实现」——照做会删掉活代码。修复后 `frontend/src/shared/**` 的
    `publishMarketCandidates` / `fetchBrokerRecommendations` / `parseApiData` 等全部归位。
  - `OE-06` 别名导入：`import { X as Y }` 记为消费 `Y`。`SettingsBoard.tsx:10` 的
    `MarketBrokerMappingSection as MarketBrokerMappingComponent` 使活组件被判「真实零引用」。
  - `OE-06` fix_hint 措辞：剩余 81 项「仅本文件使用」的导出，原措辞同样会误导成删实现。
  - `PF-01` 头部迭代表达式：`for r in cursor.fetchall():` 的 `fetchall` 只求值一次，
    却被 whole-loop walk 计入。9 项中 **3 项**误报（`bdib_health.py:139` / `fills.py:270` /
    `raw_fills.py:113`，逐条核对 body/orelse 后确认 body 内无 IO）。

- **工具缺陷（非规则误报，独立发现）**：`cleanup --ruleset <cl|pf>` 仍写 `scans` 趋势记录
  （`n_findings=0`）→ `last_full_scan()` 取到虚假 0 项基准，实测到
  「环比上次全量（…）: findings **0 → 217**」与趋势表 0 行。

- **性能候选实测状态（本轮未新增实测，沿用历史结论并显式标注）**：
  - 服务未运行（3000 / 5173 / 8001 / 8002 均无监听）→ py-spy / React Profiler 本轮不可用，
    **PF-xx 一律维持「静态候选 · 待实测」**，不声称任何优化成果。
  - `PF-03` 74 项**全为 low**（medium 已于 2026-09-10 实测清空至 0）；
    `PF-07` 47 项已于 2026-09-10 用 MutationObserver 实测（317 次 mutation / 0 个 >50ms 长任务）
    → **当前数据规模下不构成瓶颈**，属规模增长后的潜在项。
  - `PF-06` 榜首 `_mktdata_subscription_loop`（热度 2688.4）**已不是性能问题**：代码确认
    `enrichment.py:162-171` 已做 housekeeping 周期化节流，2026-09-11 实测空闲 CPU 14.4% → 0.2%；
    热度分反映的是**结构复杂度**（CC 58 / 嵌套 12），与 OE-05 完全重合。
  - `PF-06 ∩ OE-05` 同点交叉 **10 处**（`_evaluate_route_item`、`_validate_split_totals`、
    `bloomberg/adapter.py:229 get_orders`、`connection.py:99 connect`、`_mktdata_subscription_loop`、
    `_subscription_loop`、`_process_subscription_message`、`_process_route_message`、
    `order_projections.py:18 enrich_orders`、`anomaly_query.py:343 query_anomaly_routes_page`）
    → 两套规则集独立指向同一批函数，**信号强于任一单套**，建议按「可维护性拆分」立项，
    而非按性能优化（后者须先有 profiler 证据）。
  - `PF-04` 唯一项 `orders_execution.py:38 _parent_store` 经核实为**文档化的进程内 mock**
    （文件头写明「replaced by real DB session in production」）→ 处置建议为 **suppress + 待办注释**，
    而非加 LRU（加淘汰会改变 mock 语义）。

- **分级偏差**：无。本轮未调整任何 `config.py` 阈值；`PF-01` 3 项误报原本被定为 **medium**，
  说明「medium 不一定真」——再次印证静态候选必须实测。

- **规则/阈值变更**：无阈值变更；实现层变更为
  `frontend_light.py`（`_scan_multiline_clauses` + `_parse_source_names` / `_parse_binding_names` + fix_hint）、
  `perf.py`（`_io_calls_in_executed`）、`cleanup/cli.py`（`_is_full_coverage`）。

- **验证**：`pytest scripts/quality_gate/tests scripts/cleanup/tests` → **69 passed**（新增 5 个用例：
  跨行 import / 跨行 re-export / 别名导入 / for 头部非 IO / while 条件仍判 IO + 部分扫描不入库）；
  `quality_gate --quiet`：AP 违规 0 / OE 存量 187 / 债务 167.79h；
  `cleanup --report`：清理项 0 / 性能项 199 / 热点 15 / 存量清偿率 44%。

- **基线口径警示**：本轮 `fixed` 172 项中含 **75 项是「检测器修复导致的消失」**
  （71 + 1 + 3），**不代表真实清偿**。历史同类修复（PF-03 的 21→1、PF-08 正则）
  也应以同一口径扣除后再解读清偿率。

- **未执行（需授权 / 需环境）**：① 任何生产代码删除（CL=0 无对象；OE 侧 5 项真实零引用
  `monitoring-metrics.py::MetricNullReason`/`TcaMetricName`、
  `settings-nav.test.tsx::measure`、`shared/lib/format-utils.ts::fmtPct`、
  `shared/services/token-service.ts::getAuthHeaders`，与 81 项 export 冗余，全部待人工确认）；
  ② PF-01 已实测确认的 6 项 N+1（`fills.py:353`、`bdib_health.py:179`、`report_aggregator.py:396`、
  `report_dims.py:59`、`query_cli.py:189`、`quality_gate/store.py:107`）的改写与 before/after 计时；
  ③ 外部工具（knip / vulture / py-spy / EXPLAIN QUERY PLAN）。

- **遗留提示**：`OE-06` 仍存在「同文件使用型」误报（见遗漏候选段）；
  `cleanup` 趋势库中留有一次 `--ruleset cl` 造成的 0 项历史记录（口径已修，历史行未清理）。

### 2026-09-15 · 全库清理（**授权执行**：用户「最高权限：识别和移除过时冗余」）

- **模式与规模**：全库 / 强度=执行删除；379 文件 / 34,412 行 Python；CL 命中 **0** / PF 命中 216（含 PF-06 15）
- **并集侧**：`quality_gate --ruleset oe` 存量 **188 → 178**（−10，全部来自 OE-06 前端零引用导出）
- **实际删除**（分 4 批，批间全量回归）：
  - **B1 未使用 import（Python，41 处 / 26 文件）**：AST 判定零引用（含字符串注解兜底）+ 词边界全仓复核 +
    re-export 面识别；`50 → 9`（剩余 9 项为**有意保留**的兼容 re-export 面，见「保留判定」）
  - **B2 前端零引用导出（10 处 / 8 文件）**：`ViolationTooltip`、`hasBrokerStrategiesInFile`、
    `hasStrategyInfoInFile`、`triggerUpdate`、`TcaMetricName`、`MetricNullReason`、`METRIC_NULL_REASON`、
    `fmtPct`、`measure`、`token-service.getAuthHeaders`（后者与 `shared/services/http-client.ts` 同名**重复实现**）
  - **B3/B4 类方法零引用（Python，34 处 / 8 文件）**：`data_access/storage/repositories/fills.py` 14、
    `raw_fills.py` 4、`market_store.py` 7（含 `get_market_context` + 5 个仅供其调用的 helper）、
    `repositories/_base.py` 1、`CostView/src/tca_query_service.py` 4、`backend/api/repositories/parent_child_repository.py` 4、
    `platform_data/contracts/boundary_registry.py` 4、`platform_data/adapters/redis_handoff.py` 1
  - **级联清理**（删除后复扫暴露，正是「级联失效」条目所述）：`MarketStoreReader.get_distinct_dates` /
    `get_distinct_tickers`、`SqliteFillReadRepository.get_processed_dates`
  - **B5 临时遗留文件（CL-07，2 个）**：仓库根 `_tmp_qg.txt`、`frontend/_tmp_vitest.log`（均未跟踪）
  - **合计**：39 文件改动 / **−750 行**（16 行新增为 import 语句保留部分）
- **保留判定（未删，逐条写明理由）**：
  - `platform_data/adapters/tca_bridge.py` 的 5 个 contract 类型 + 2 个 db 常量 import —— 紧邻「Re-export constants
    from canonical location」注释块，属**显式声明的兼容 re-export 面**，删则破坏对外可访问性；
  - `CostView/src/tca_query_service.py:439` 的 `TcaOrderSummary/TcaRouteDetail` —— 注释明写「兼容旧导入」
    且带 `# noqa: E402,F401`，属显式兼容面；
  - 前端 **68 项「仅本文件使用」的 `export` 关键字**（25 文件）—— 与规则 fix_hint 一致但**本轮不执行**：
    `components/ui/*` 3 项属 shadcn 上游生成面（重新 `shadcn add` 会回退），其余多为 `types.ts` / `services/*.ts`
    的**类型词表**（模块存在目的即导出类型），收益为纯表面收敛、成本为 25 文件噪声 diff 与 DX 退化，
    按「收益/风险比」暂缓，清单已产出待人工决策；
  - `scripts/ci/blpapi_stub/blpapi/__init__.py` 3 个方法 —— 第三方 API 桩（`EMPTY_STUB_EXEMPT_PATH_PARTS` 先例）；
  - `platform_data/contracts/data_access.py` —— ADR-0013 规划中契约，`DEAD_FILE_EXEMPT` 既有豁免。
- **跨仓库确认（第三轮质询）**：`data_access/` 侧删除沿用 2026-09-10 的决定性证据（管道仓库全量检索
  `data_access` 0 命中，其 README 自述不依赖本仓库代码树），本轮未发现新证据推翻该结论。
- **独立复核（不依赖 cleanup 检测器）**：CL-08 全仓 0；CL-09 唯一命中为
  `scripts/cleanup/tests/test_cleanup.py:190` 的**检测器测试夹具**（刻意构造的注释代码块，保留）；
  CL-07 命中 2 项均已删除（见 B5）。
- **误报（工具报出/漏报，经核实）**：
  - **漏报**：`tca_query_service.py` 的 4 个 `_*_conn` helper 中 `_fill_bdib_conn` 被
    `tca_query_builder.py` 的**同名模块级函数**遮蔽 → 审计脚本判其存活；人工核实后一并删除
    （同批 `import sqlite3` 级联失效，已删）
  - **漏报**：`get_distinct_dates` 被 `get_distinct_dates_in_range`、`get_processed_dates` 被
    `get_unprocessed_dates` **子串遮蔽** → 删除首批后复扫才暴露（见「高频误报段」新增两行）
- **分级偏差**：本轮 PF 命中 **216 → 190（−26）** 并非性能优化成果 —— 其中 **PF-03 75 → 51（−24）**
  全部来自被删死方法内的无界 `SELECT *`（移除死代码即移除候选）。**口径警示**：PF 数量变化必须区分
  「真实优化」与「死代码消失」，否则会虚报收益。
- **规则/阈值变更**：无（`config.py` 未改）。工具层建议已入「高频误报段」：类方法判定需词边界匹配 +
  同名实体区分，建议内置为 `CL-12`。
- **验证**：批间与收尾均跑 `pytest backend CostView scripts/quality_gate/tests scripts/cleanup/tests`
  = **464 passed / 1 skipped**（与改动前基线一致）；`compileall` 全仓 exit 0；`tsc -b` exit 0；
  `vitest run` **19 文件 / 155 用例全绿**；`cleanup --report` 清理项 **0**；`quality_gate` AP 违规 0。
- **文档同批修订**：`scripts/README.md`（原描述含**已不存在的** `_archive/`、`workflow/` 与已迁出的
  `ops/import_excel_fills.py`、`ops/sync-metrics.py`、`backfill_raw_fills_oaod_eet.py`，且漏记
  `ci/`、`cleanup/`、`quality_gate/`、`reports/`、`devtools/wt-*.ps1` → 按实际目录重写）。
  历史记录（`docs/archive/**`、`specs/**`、`docs/spec/adr/**`）按纪律**未改**。
- **未执行（需人工确认 / 需授权）**：
  1. 前端 68 项多余 `export` 关键字的收敛；
  2. `scripts/reports/quality_gate/report-20260915.md` 已被 git 跟踪，但 `.gitignore` 策略
     （`report-*.md` 忽略 + 注释「历史快照保留在版本库内**不再新增**」+ 「避免双账本」）与之冲突
     —— 属**有意提交**的生成物，不擅自删除，待人工决策；
  3. 外部工具 knip / vulture / deptry / radon 仍未安装（本轮以自建 AST 审计替代，结果已交叉核对）。

### 2026-09-15 · 收尾批次（授权后：CL-12 内置 + 前端 export 收敛 + 生成物出库）

**范围**：接上一轮（同日「全库清理」）的三项遗留 + 一项新规则。**这一批的边际价值主要在机制**：
把上一轮靠临时脚本做的类方法判定**固化为可重复的门禁规则**，并顺手完成前端公开面收敛与一条
与 `.gitignore` 策略冲突的生成物出库。

**1. 新增 `CL-12` 过时类方法（零引用）** —— 见 [ADR-0019](../../../../docs/spec/adr/0019-cl12-dead-class-method-detection.md)

- **实现**：`scripts/cleanup/detectors/dead_methods.py` + `config.py` 阈值/豁免 + `CL_DETECTORS` 注册；
  自测 `TestDeadMethods` **12 用例**（含 2 条真实漏报的回归：`get_x` vs `get_x_y` 子串关系、
  模块级同名函数 vs 类方法的实体归属）。
- **两条关键设计**（均由上一轮实测漏报反推）：
  - **词边界匹配** `(?<![\w.])name(?![\w])` —— `_` 属 `\w`，`get_x` 不再被 `get_x_y` 遮蔽；
  - **同名实体区分** —— 文件自带同名模块级符号时，其内裸标识符归属自有符号，仅 `obj.name` 属性访问计为引用。
- **首轮实测（真实仓库）**：产出 **14 项**候选，其中 **1 项为真误报**（
  `ConnectionManager.close_thread_cached_connections` —— docstring 明写「Deprecated no-op…保留以兼容旧调用点」，
  按 CL-05 既有口径应豁免）→ **已补 docstring 占位/兼容 no-op 豁免**并加单测。
- **三轮质询结论**：
  - **删除 10 项**（约 130 行）：`ParentChildRepository.{create_parent, update_parent_filled, create_slice}`、
    `ConnectionManager.{get_admin_connection, get_all_paths, get_existing_databases}`、
    `MarketStoreReader.get_row_count`、`SqliteFillReadRepository.get_fills_for_date`、
    `SqliteRawFillReadRepository.{get_fills_for_date, get_row_count}`；
    其中 `get_admin_connection`（docstring 已标 `.. deprecated:: 010-extract-pipeline`）属写/管理能力，
    删除与 2026-09-10 删 `backup_database` 同理，**强化 ADR-0016 只读边界**；
  - **保留 4 项并新增 `DEAD_METHOD_EXEMPT_NAMES` 收口**：`HandoffExchangeAdapter` 与
    `RedisHandoffExchangeAdapter` 的 `clear_market_to_execution` / `clear_cost_to_execution`
    —— 三轮质询第三轮**命中**：`.codebuddy/rules/module-boundary.md` §2.3 明确列为「外部可见方法」，
    是已文档化的适配器公开面。**这是本批唯一一次「工具报出但必须保留」**，也验证了三轮质询的必要性。
- **跨仓库质询（本轮首次可直连取证）**：发现管道仓库在 `Documents/EMSXDataPipeline`（兄弟目录），
  233 个文件直扫结论 ——
  - 对本仓库代码树的 import **仅 1 处**且为**悬空引用**（`runner/diagnostics.py:84`
    `from platform_data.database_diagnostics import init_diagnostics_db`；该模块在本仓库**不存在**，
    管道仓库亦无自带 `platform_data/`）→ 前几轮「管道不消费本仓库代码」的结论**得到直接证实**；
  - 上一轮删除的全部符号在管道仓库中的命中**均为其自有副本的定义**（如
    `DataPipeline/storage/market_store.py` 自带 `get_market_context` / `verify_integrity` / `get_distinct_dates`，
    `DataPipeline/storage/repositories/fills.py` 自带 `get_processed_dates` / `get_unprocessed_dates` …），
    **不是引用** → 跨仓库安全性从「记录在案的历史结论」升级为「当轮直接取证」。

**2. 前端「仅本文件使用」的多余 `export` 收敛（65/68）**

- **做法**：逐个定位声明行去掉 `export ` 前缀（只改关键字、不动实现），
  `tsc -b` exit 0 + `vitest run` **19 文件 / 155 用例全绿**验证无断裂。
- **保留 3 项**（`components/ui/{badge,popover,scroll-area}` 的
  `badgeVariants` / `PopoverAnchor` / `ScrollBar`）：三者是 shadcn **上游分组导出面**
  （`export { Badge, badgeVariants }` 形态），且 `ScrollBar` 是 `ScrollArea` 的**组合原语**；
  收敛会在下次 `shadcn add <component>` 时被上游模板覆盖回退，属**无持久收益的 churn**。
- **口径**：这不是「删代码」，而是收窄模块公开面；68 项全部为「本文件内部有引用」，
  故 fix_hint 始终是「去掉多余 export 关键字，**切勿删除实现**」。

**3. 生成物出库（按 `.gitignore` 既有策略）**

- `scripts/reports/quality_gate/report-20260915.md` 已 `git rm` 出库。
  依据 `.gitignore` 第 81-84 行的明确策略：`report-*.md` 忽略 + 注释写明
  「20260821/20260825 为历史快照，保留在版本库内**不再新增**」+「逐轮修复账本以
  `docs/report-tca-known-limitations.md` §五 为准，**避免双账本**产生『哪份是真相』分叉」。
  出库后该路径由忽略规则接管（`git check-ignore` 对新文件已生效，历史两份快照保留）。

**4. 文档同批修订**

- 新增 `docs/spec/adr/0019-cl12-dead-class-method-detection.md`；
  `docs/spec/memory.md` 索引补 ADR-0019，并在 ADR-0017 行标注「类方法零引用判定由 ADR-0019 扩展」
  （沿用 ADR-0015 → 0018 的**索引行标注**惯例，**不改 ADR 正文**）；
  `docs/spec/adr/README.md` 补 0018（此前缺登记）与 0019；
- skill 侧：`ruleset-cl.md` 增 CL-12 全节（判定 / 两条关键设计 / 豁免 / 分级 / 验证 / 已知边界）、
  `tool-matrix.md` 把 vulture 从「负责类方法」降级为「可选交叉核对」、
  本文件「遗漏候选段」与「高频误报段」相应收口。

**5. 验证**：`pytest backend CostView scripts/quality_gate/tests scripts/cleanup/tests`
→ **477 passed / 1 skipped**（较上批 464 增加 13 项 CL-12 新用例）；`compileall` exit 0；
`tsc -b` exit 0；`vitest run` 155 通过；`cleanup --ruleset cl` **清理项 0**（引入 CL-12 时首批 14 → 收口后 0）；
`audit_doc_drift.py` 无漂移。

**6. 跟进批次（同日，授权后）**：`CL-12` 接入 CI 日常路径 + 收口最后 9 项 re-export 面 + shadcn 3 项

- **`CL-12` 真正进入日常门禁**：此前 `cleanup.py` 只在人工执行时运行（pre-commit 只跑
  `quality_gate --staged`，不含 cleanup 规则集）→ 新增 `.github/workflows/cleanup-report.yml`，
  每个 PR / push 全量运行并把结果写入 Job Summary + 上传产物（**建议性、不阻断**，
  沿用既有 `doc-drift-report.yml` 的 `continue-on-error` + Summary + artifact 模式）；
  摘要渲染抽为 `scripts/cleanup/summary.py`（4 项单测，含「缺文件不失败」的 CI 友好约束）。
- **`--strict` 评估结论 = 暂不开启**（三条理由 + 三条切换条件写入 workflow 头注释与
  `ruleset-cl.md`「CI 集成与 `--strict` 门槛」）：核心障碍是 `--strict` 语义为
  「基线外新增项阻断」而**基线库被 .gitignore 排除** → CI 全新鲜克隆下基线为空，
  会把全部存量项判为新增；且误报收口不能依赖 `--suppress`（记录在未入库的库里）。
- **最后 9 项未使用 import 收口**（`tca_bridge.py` 7 项 + `tca_query_service.py` 2 项）：
  双仓库 AST 核查（**408 个 .py**：本仓库 + EMSXDataPipeline）确认**零消费者** ——
  命名空间历史上是 re-export 面，但实际消费者只从 `platform_data.contracts` 导入。
  移除 + 同步 `docs/spec/module-api-contracts.md`（注明兼容 re-export 已退役、
  两个 deprecated 类型仍由契约包导出）。`tca_bridge` 的常量注释同步改写为
  「本模块不再承担 re-export 职责」。
- **shadcn 3 项收敛（`badge`/`popover`/`scroll-area`）**：三者是**分组导出**
  （`export { A, B }`）形态，故走列表裁剪；其中 `PopoverAnchor` 裁剪后 `tsc -b` 立即报
  `TS6133 声明未使用` → 证明它此前**仅靠 export 维持「被使用」**，遂整体删除组件实现
  （6 行）。**这是一条新的口径提醒**：`own>1` 的「仅本文件使用」判定会被
  **导出语句本身**计入，应扣除 export 行再判（已记入「遗漏候选段」）。
- **验证**：`pytest` **481 passed / 1 skipped**（+4 摘要单测）；`tsc -b` exit 0；
  `vitest run` 155 通过；`cleanup --ruleset cl` 清理项 0；workflow YAML 本地解析通过。

**7. 观察窗口复盘（同日，CI 已在 5 个 PR + 3 次 push 上运行）→ 发现并修复一个跨平台缺陷**

**先看数据再看结论**：从 CI 日志重建 cleanup JSON 后发现 —— **CL 并非 0，而是 166 项 CL-10**
（本地 Windows 恒为 0）。即：**CI 作业上线首日就抓到一个本地不可复现的系统性误报**，
这正是「先跑几轮观察」的价值，也**直接否决了当时切 `--strict` 的可行性**
（若已切，每个 PR 都会被 166 项误报阻断）。

- **根因**：`cleanup/detectors/frontend.py::_normalize` 丢弃全部空片段（**含 POSIX 根 `/`**）：
  `/repo/frontend/src/a` → `repo/frontend/src/a`，与 `Path.as_posix()` 产出的 `/repo/...`
  **永不相等** ⇒ 前端 import 图的**所有边在 Linux / CI 上丢失** ⇒ 除入口外全部被判「不可达」。
  Windows 本地因盘符 `C:` 占据首个非空片段而**恰好不暴露** —— 典型「只在 CI 复现」缺陷。
- **影响面（不止 CL-10）**：同一实现被 `quality_gate/detectors/frontend_light.py`
  **复制了一份**，故 OE-01（前端死模块）与 OE-06（未使用导出）在 Linux/CI 上同样失真。
  此前未被发现的原因：quality_gate 只在**本地 Windows**（pre-commit）运行，CI 只跑 audit 脚本。
- **修复**：把路径工具**收敛为单一实现** `scripts/quality_gate/ast_utils.py::normalize_path`
  （保留根前缀）+ `dir_of`，两处检测器改为导入；**删除两份重复实现**（符合 ADR-0017
  「不另写工具、不重复建框架」）。
- **回归用例（5 个）**：`ast_utils.normalize_path` 保留 POSIX 根 / 消解 `..` 与 Windows 分隔符 /
  `dir_of`；CL-10 在**POSIX 绝对根**下（模拟 Linux）别名与相对说明符均能解析到绝对路径
  —— 后者在不修复时必然失败（已用旧算法逐项对照验证）。
- **经验（第三条）**：**跨平台路径工具必须显式保留根前缀**；判据是「归一化结果是否与
  `Path.as_posix()` 同形」，而不是「本地跑通」。
  **图类规则的验证必须包含 CI 计数**，因为 Windows 盘符会掩盖 POSIX 根丢失。

**8. 本批新增的三条经验**：

- **「工具报出」与「应当保留」可以并存**：CL-12 首批 14 项里，4 项是**已文档化的契约公开面**。
  删除决策的最后一关始终是**查契约文档**（`module-boundary.md`），而不是查调用方数量 ——
  零调用方的公开 API 依然是 API。
- **兄弟仓库可直接取证**：跨仓库质询过去依赖一次性人工检索记录；本轮确认管道仓库就在
  兄弟目录且可只读扫描后，把「跨仓库安全」从历史结论升级为**当轮可复现的取证步骤**；
  同时「同名副本」与「真实引用」必须区分 —— 前者恰恰是**删除安全**的证据。

### 2026-09-16 · platform_data 冗余审查与 re-export 面收敛（范围：platform_data；授权执行）

> **⚠️ 标签口径提示（追溯必读）**：本条目中出现的 **「B1 / B2 / B3」一律指执行期编号**，
> 其中 **B3 = `platform_data/__init__.py` 顶层 re-export 收敛**。用户侧方案的编号与之**不等价**
> —— 方案的「B 类」对应本条目 B1+B2，而方案无「B3」；若在别处见「B3 指
> `tca_contracts.py` 的 deprecated docstring 迁移指引」，那是**另一项**，于收尾批次落地。
> 教训见文末「收尾批次」条目：**执行中调整批次划分时，必须在报告与日志中同时写明标签定义**。

- **模式与规模**：全库基线 + 定点（`platform_data/`）；强度 = 清单 → 用户裁定 → 执行。
  CL 命中 **0** / PF 216 存量；`quality_gate --ruleset oe` 命中 16 项**全为 OE-05 复杂度**
  （`market.py::get_intraday_features` CC 66、`get_market_snapshot` CC 48）→ 转重构专项，不混入本批。
- **消费者取证口径**：AST 三节点扫描（`Name` / `Attribute` / `Constant`）覆盖全仓，
  排除 `docs/`、`scripts/reports`；**不用可能被截断的文本 grep**（沿用 2026-09-10 教训）；
  跨仓库第三轮质询直扫兄弟目录 `../EMSXDataPipeline`（233 文件，`platform_data` 侧唯一命中为
  悬空引用 `platform_data.database_diagnostics`）。
- **实际收敛（PR #50 / `9e524db`，10 文件 / +73 −69）**：
  - `platform_data/adapters/__init__.py` 公开面 **42 → 7**：移除 **8 个下划线私有符号** +
    **27 个契约类型** re-export（实现全部保留）。私有符号除「零消费者」外，另有更强的依据 ——
    `module-boundary.md` §2.3 把其中 7 个**逐字列为「内部私有（禁止跨域调用）」**，
    在包入口 re-export 与契约直接矛盾，移除即**强化**边界。
  - 两处违规消费者迁移（`module-api-contracts.md:304`「跨域数据类型只从 `platform_data.contracts` 导入」）：
    `MarketView/routers/marketview.py`（13 个契约类型）、`CostView/api/routers/costview.py`（6 个）。
  - `platform_data/contracts/__init__.py`：移除 `TcaOrderSummary` / `TcaRouteDetail` 包入口
    re-export —— 用户裁定「**只去 export、留定义**」（定义保留在 `tca_contracts.py`，
    观察一个周期后再评估删除），避免与 2026-09-15 的保留决策正面冲突。
  - `tca_bridge.get_tca_query_service()` / `config_bridge.get_config()` **docstring 漂移**修正：
    两者均声称「未注册时 fallback 到 lazy-import CostView / DataPipeline」，实现实为
    `raise RuntimeError`（该 fallback 从未实现，且会使 platform_data 反向依赖业务模块，违反 AP-01）。
- **判定反转（本轮最重要产出）**：
  - `platform_data/__init__.py` 顶层 re-export 的 8 个符号中 **7 个静态零消费者**，
    其中 `get_tca_query_service()` / `register_tca_service_impl()` 更是**零调用方**。
    但第三轮质询（**契约文档核查**）命中：`module-api-contracts.md` §平台适配器入口 与
    `data-domain.md` §使用示例把这 6 个符号逐字写成 `from platform_data import ...` 的
    **文档化公开入口** → **原 B3（顶层 re-export 收敛）整体撤销并改判 C 类**。
  - 教训强化：**「消费者计数」只能筛候选，不能定结论**；最终裁决必须过第三轮质询
    （契约文档 / 跨仓库 / 框架反射）。本次是 2026-09-15 lesson #8「零调用方的公开 API
    依然是 API」的**第二次独立验证**，且这次是**在动手过程中被自己的检查拦下**的。
  - 工具侧缺口：CL 检测器对 `__init__.py` re-export 面**零命中**（视为有意兼容面），
    该类冗余只能靠「与文档化导入规则的一致性」人工反查（本次即由 `:304` 规则反查出 27 项）。
- **保留（C 类，逐条写明理由）**：`config_bridge` / `tca_bridge` 的 DI 注册表（启动期防护）、
  `protocols.AccessTier`（DataPipeline 同名枚举镜像，duck-typing 解耦）、
  `contracts/data_access.py`（ADR-0013 规划契约，既有 `DEAD_FILE_EXEMPT`）、
  `contracts/boundary_registry.py`、`config.py::_validated_handoff_backend`（环境变量白名单校验）、
  `HANDOFF_MAX_STRATEGY_PARAMS_BYTES` 等数值真相源（契约测试锁定）。
- **归档反序列化路径取证（第三轮质询第三维，收尾批次补做）**：仓库内 `pickle` / `marshal` /
  `joblib` **0 使用**；数据根（`${EMSXVIEW_DATA_DIR}`，本机 `D:\db`）**无 `.pkl`**，
  文本候选 18 个（17 `.json` + 1 `.csv`）对 `TcaOrderSummary` / `TcaRouteDetail` **0 命中**；
  `redis_handoff` 的「按字段名重建」只覆盖 handoff / market 契约。→ 该维度当前**无消费者**，
  剩余不可扫描面仅限仓库与数据根之外的临时手工导出。
- **未执行**：`market.py` 两处复杂度（CC 66 / 48）属 OE-05 重构专项；
  `market.py:403/417`、`tca_bridge.py:127`、`regime_query.py:62` 4 处无界读取属性能实测专项。
- **验证**：`compileall` exit 0；backend **191 passed**（边界 15 passed / 1 skipped）；
  CostView **219**；MarketView **12**；门禁自测 **91**；
  `audit_cross_imports` / `audit_underscore_access` / `audit_db_paths` / `audit_doc_drift` 全通过；
  `cleanup --ruleset cl` 清理项 **0**；CI 4 项检查全绿后 squash 合并、worktree 与分支已清理。

### 2026-09-16 · platform_data 收敛收尾批次（用户复核结论落地）

- **背景**：用户复核 PR #50 / #51 后判定「整体通过」，同时提出两项收尾：(1) `tca_contracts.py`
  两个 deprecated 类型的 docstring **未**补「已不再从包顶层 re-export」的迁移指引；
  (2) 「B3」标签在执行清单与方案间**指代不同对象**，需明确口径。
- **落地**：
  - `platform_data/contracts/tca_contracts.py`：`TcaRouteDetail` / `TcaOrderSummary` docstring
    补迁移指引（显式子模块导入示例 + 定义保留观察期说明）—— 使 deprecated 契约**自描述**，
    不必依赖 `contracts/__init__.py` 的注释或外部文档才能得知包顶层已不再导出。
  - 上一条目补「⚠️ 标签口径提示」+ 归档反序列化取证结论（见该条目）。
- **教训（新增，值得固化）**：**跨会话交接的「编号」是易失契约**。同一次任务中，
  「执行清单编号」与「方案编号」可能错位：本案执行期把方案 B 类拆成 B1+B2、并在执行中
  撤销原 B3、另立 C 类判定，而用户侧对 B3 的指代落在 `tca_contracts.py` docstring 上。
  → 凡在执行中**调整批次划分**（拆分 / 撤销 / 改判），必须在**产出报告 + 迭代日志**中
  **同时写明标签定义**；否则下一轮追溯会把两个 B3 混为一谈。这是一类与代码无关、
  但会造成返工的沟通缺陷，成本高于代码本身。

