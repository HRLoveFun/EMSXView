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

---

## 遗漏候选段（已知能力边界，未实现）

| 能力缺口 | 现状 | 替代手段 |
|---|---|---|
| 类方法的零引用判定 | CL-02 只判模块级符号 | vulture `--min-confidence 80` |
| 跨文件重复代码块 | 由 `quality_gate` OE-04（AST 归一化整函数匹配）覆盖 | 直接跑 `quality_gate --ruleset oe` |
| 未使用的 npm / pip 依赖 | 未实现 | knip（JS）/ deptry（Python） |
| 前端打包体积归因 | 未实现 | `vite-bundle-visualizer` |
| 运行时热点测量 | 刻意不做（静态工具不得冒充 profiler） | py-spy / cProfile / tracemalloc / React Profiler |
| 数据驱动的索引缺失 | 只做 SQL 文本静态提示 | `EXPLAIN QUERY PLAN`（唯一权威） |
| `quality_gate` 扫描范围漂移 | `quality_gate/config.py::PYTHON_SCAN_ROOTS` 仍含已迁出的 `DataPipeline`，且**缺 `data_access`** → OE-01/02/04/05 对 `data_access/` 整层（本仓库发现数最多的模块，66 项）零覆盖 | 建议同步扫描根；因会新增大量基线项，需单独评估后执行（不在本次清理授权内） |
| `parse_module` 静默失败 | 解析失败（如 BOM / 语法错误）与「无 import 边」不可区分，图类规则会静默误报 | 已修 BOM 根因；后续可让检测器把「解析失败文件」单独列为提示项 |
| 行号型指纹的产生抖动 | 位置级规则（`nested@{line}` / `comment@{line}` / `unreachable@{line}`）在无关行增删后会换 fingerprint，被记为「新增 + 清偿」各若干 | 属设计取舍（位置即身份）；批量编辑工具文件时会出现个位数抖动，可忽略；如需消除可改为内容片段哈希 |
| 级联失效 | 删除一个文件会让「仅供其使用」的下游符号新变为零引用（本次 `exchange_tz.batch_convert_ny_to_local` 即如此） | 删除批次完成后**必须复扫一次**再定下一批，勿按首轮清单一次性删完 |

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
