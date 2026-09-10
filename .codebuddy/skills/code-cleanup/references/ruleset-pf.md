# 性能规则集（PF-xx）

> 检测实现：`scripts/cleanup/detectors/perf.py`、`detectors/frontend.py`
> 阈值唯一真相源：`scripts/cleanup/config.py`

**共同前提**：PF-xx 产出的是「**值得实测的可疑模式**」，不是性能缺陷。
任何优化动手前必须完成「阶段 4」的测量闭环，并给出前后对比数字。
反过来说：**未命中也可能是真热点**（profiler 才能给出真相）——PF-xx 的价值是排序，不是覆盖。

---

## 全表

| ID | 名称 | 目标 | 判定方式 | 严重度 |
|---|---|---|---|---|
| PF-01 | 循环内 IO/查询（N+1） | 耗时 | 循环体内出现 `execute`/`executemany`/`fetch*`/`read_sql`/`to_sql`/`commit`/`flush`，或 HTTP 调用（`client.get` 等，需接收者名含 client/session/requests/http/api/url） | 2 层 medium / 嵌套 high |
| PF-02 | 嵌套循环 O(n²) / 线性扫描 | 耗时 | 循环嵌套 ≥2 层；或循环内 `.index(` | 2 层 low / ≥3 层 medium |
| PF-03 | 全量加载 / 无界读取 | 内存 | 无 `LIMIT` 的 `SELECT *`；`fetchall`/`readlines`；pandas `read_*` 无 `nrows`/`chunksize` | `SELECT *` medium / 其余 low |
| PF-04 | 只增不减的累积容器 | 内存 | 模块/类级容器在函数体内以数据驱动方式增长，且全模块无淘汰/上限证据 | medium |
| PF-05 | 循环内字符串拼接 | 耗时 | 循环内对字符串做 `+=`（O(n²) 拷贝） | low |
| PF-06 | 热点候选（需 profiler 实测） | — | 热度分 = 行数 × (1 + 嵌套/2 + CC/10 + 循环数)；超长文件另计 | low（非缺陷） |
| PF-07 | 前端渲染热点 | 耗时 | `key={index}`；`.map` 中内联对象/函数字面量 | low |
| PF-08 | Context Provider 未 memo 化 | 耗时 | `<X.Provider value={{ ... }}>`（父组件每次渲染触发全树重渲染） | medium |
| PF-09 | WHERE 列被函数包裹导致索引失效 | 耗时 | SQL 中 `WHERE <func>(col) = ?`（substr / lower / upper / cast / date / length / trim …） | medium |

---

## PF-01 循环内 IO / 查询（N+1）

**为什么最重要**：单次 IO 的固定开销（网络 RTT、SQLite 解析+锁、HTTP 建连）乘以循环次数，
是后端最典型的延迟放大器；在 Bloomberg/Redis/PostgreSQL 场景下，1000 次往返 ≈ 秒级延迟。

**固定命中**：`execute` / `executemany` / `executescript` / `fetchone` / `fetchall` / `fetchmany` /
`read_sql*` / `to_sql` / `read_csv` / `read_parquet` / `read_excel` / `commit` / `flush`。

**条件命中**：`get` / `post` / `put` / `patch` / `delete` / `request` / `send` —— 仅当接收者名字命中
`client|session|requests|httpx|http|api|url|resp|endpoint` 时才判定（否则会误报 `dict.get`）。

**修复手段**：

| 场景 | 手段 |
|---|---|
| SQL 逐 id 查询 | `WHERE id IN (?, ?, ...)` 批量；或临时表 JOIN |
| SQL 逐行写入 | `executemany` + 单事务（同时消除逐行 commit 的 fsync 开销） |
| HTTP 逐条请求 | 批量端点 / 并发池（`asyncio.gather` + 信号量）/ 本地缓存 |
| 循环内 `commit()` | 提到循环外，一次事务提交 |

**实测**：`EXPLAIN QUERY PLAN`（确认索引命中）、`py-spy record --subprocesses`（确认热点在 IO 等待）。

---

## PF-02 嵌套循环 O(n²) / 循环内线性扫描

**判定**：循环嵌套 ≥2 层（2 层判 low——小集合遍历极常见；≥3 层判 medium）；或循环内出现 `.index(`。

**修复手段**：

- 内层查找 → 循环外预建 `set` / `dict` 索引，把 O(n) 降为 O(1)；
- 数值/矩阵运算 → `numpy` 向量化或 `pandas` merge（本仓库 `data_access/` 已有 numpy 依赖）；
- 双集合求交/差 → 集合运算替代双层遍历。

**豁免**：内层确为常量级小规模（如固定 4 个交易所、12 个月），`--suppress` 并注明理由。

---

## PF-03 全量加载 / 无界读取（内存）

**判定**：

1. SQL 字符串含 `SELECT *` 且无 `LIMIT` → **medium**：既浪费带宽也放大内存，还让索引无法覆盖；
2. `fetchall()` / `readlines()` → low：一次性把结果集搬进内存；
3. pandas `read_csv` / `read_parquet` / `read_sql` 未指定 `nrows` / `chunksize` → low。

**本仓库语境**：分析型 SQLite 表可达数千万行（`raw_fills`、`raw_bdib` 等），
`fetchall()` 在分析查询上属于真实的内存风险；`data_access/` 为只读消费者，只能靠 `LIMIT`/分页/列裁剪降载。

**修复手段**：

- 列裁剪：只 SELECT 需要的列（同时让覆盖索引生效）；
- 分页：keyset 分页（`WHERE id > ? ORDER BY id LIMIT ?`）优于 `OFFSET`；
- 流式：`chunksize=` 分块聚合，或游标逐行；
- 下推：过滤/聚合尽量下推到 SQL（对齐项目约定「TCA 指标读预计算表，禁止查询时实时聚合」）。

**实测**：`EXPLAIN QUERY PLAN`；`tracemalloc` / `memory_profiler` 取峰值 RSS。

---

## PF-04 只增不减的累积容器

**判定**：模块级/类级 `{}` `[]` `set()` `dict()` `defaultdict()` `deque()` 容器，在**函数体内**以
数据驱动方式增长（`容器[动态键] = ...`、`.append/.add/.update/.setdefault` 非全常量参数），
且整个模块内不存在淘汰/上限证据（`.pop/.clear/.popleft/popitem`、`del`、`len(x) >`、`maxlen=`、`maxsize=`）。

**自动豁免**：

- 名称含 `registry` / `impl(s)` / `factor(y|ies)` / `singleton` —— 条目数由「实现数量」而非数据量决定，天然有界；
- 全常量键写入（`REGISTRY["default"] = impl`）；
- 仅在 import 期一次性填充（无函数内增长）。

**为什么重要**：长跑进程（后端服务、MCP server、hook）里的无界 dict 是最隐蔽的内存泄漏形态——
没有引用环、没有异常，只是 RSS 单调上升。

**修复手段**：`functools.lru_cache(maxsize=)`；`deque(maxlen=)`；显式 maxsize + FIFO/LRU 淘汰；
或改用 TTL 缓存 / 外部存储（Redis）。

---

## PF-05 循环内字符串拼接

**判定**：循环体内 `name += ...`，其中右侧是字符串常量，或 `name` 在本函数内曾被赋字符串常量。

**修复**：累积 `list` 后 `"".join(parts)`；大文本用 `io.StringIO`。

---

## PF-06 热点候选（需 profiler 实测）

**热度分** = `函数行数 × (1 + 嵌套深度/2 + 圈复杂度/10 + 循环数)`，低于阈值不输出，全局取 Top-N；
文件行数超阈值时另出一个文件级候选。

**定位**：这是**排序工具**，用于决定「先测哪个」，不是缺陷清单。
处理顺序建议：文件级超长 → 函数级高热度 → 实测确认 → 才考虑拆分/缓存/改算法。

---

## PF-07 前端渲染热点

**判定**：

- `key={index}` / `key={i}` / `key={idx}` —— 列表重排/删除时整段重渲染且组件状态错位；
- `.map(` 渲染中出现内联对象字面量 `={{ ... }}` 或内联箭头函数 `={() => ...}` —— 每次渲染新建引用，
  使子组件的 `React.memo` / `useMemo` 依赖比较永久失效。

**修复手段**：稳定业务 id 作 key；把对象/回调提到组件外或用 `useMemo`/`useCallback` 稳定引用；
长列表（数千行）引入虚拟化（`react-window` / `@tanstack/react-virtual`）；
高频数据流（订单/路由流）下沉到 Zustand store + selector 细粒度订阅，避免写进全局 Context。

**实测**：React DevTools Profiler 记录 commit 次数与渲染耗时。

---

## PF-08 Context Provider 未 memo 化

**判定**：`<X.Provider value={{ ... }}>` —— `value` 是对象字面量，父组件每次渲染都产生新对象，
**全部消费者组件无条件重渲染**。

**修复**：`const value = useMemo(() => ({ a, b, setA }), [a, b])`，依赖项收敛到真正变化的字段；
或按关注点把单个大 Context 拆成多个小 Context（高频字段与低频字段分离）。

**注意**：这是"高频数据流不得写入全局 Context"的项目约定的静态体现
（见 `CODEBUDDY.md`「前端状态管理」）。

---

## PF-09 WHERE 列被函数包裹导致索引失效（sargability）

**实测证据**（2026-09-10，只读 `EXPLAIN QUERY PLAN`，数据根 `D:\db`）：

| 表 | 规模（max(rowid)） | WHERE 形态 | 执行计划 |
|---|---|---|---|
| `raw_fills` | **14,338,234** | `substr(order_as_of_date, 1, 10) = ?` | **`SCAN raw_fills`（索引失效）** |
| `raw_fills` | 同 | `source_date = ?` | `SEARCH ... USING INDEX idx_raw_source_date` |
| `processed_fills` | **74,713,724** | `SELECT *`（无 WHERE） | `SCAN processed_fills` |
| `processed_fills` | 同 | `order_as_of_date = ?` | `SEARCH ... USING INDEX idx_proc_date` |

**为什么坏**：SQLite 只能对「未被函数包裹的列」使用列索引 → 前者退化为全表扫描。
在千万行级表上，这直接决定查询是毫秒级还是分钟级。

**修复手段**：

- `substr(col, 1, 10) = ?` → `col >= ? AND col < ?`（日期前缀比较等价改写）；
- `lower(col) = ?` → 建表达式索引 `CREATE INDEX ... ON t(lower(col))`，或改存规范化列；
- `date(col) = ?` → 存独立日期列，或改范围条件。

**验证**：`EXPLAIN QUERY PLAN` 必须由 `SCAN` 转为 `SEARCH`；若已存在表达式索引则豁免并注明。

**同源发现（系统级）**：全部业务库**均无 `sqlite_stat1`**（从未执行 `ANALYZE`）→
查询计划器缺少统计信息，在七千万行级表上可能选错计划。建议在数据维护侧（独立仓库
EMSXDataPipeline）的例行流程中加入 `ANALYZE`，本仓库作为只读消费者不执行该语句。

## 性能优化的四步闭环（强制）

```
1. 测量基线   py-spy record / cProfile / tracemalloc / EXPLAIN QUERY PLAN / React Profiler
2. 定位根因   确认是算法、IO 往返、索引缺失、渲染次数还是内存驻留
3. 单一改动   一次只改一个变量，改完立刻复测（避免"改了一堆、不知谁有效"）
4. 固化基线   把前后数字写进报告/提交信息；把可回归的指标落 pytest-benchmark 或 CI 断言
```

**禁止**：未测量就"顺手优化"；为微秒级收益引入缓存/并发等复杂度（镀金，见 ADR 与
[`plan-design-principles.md`](../../../docs/spec/plan-design-principles.md) P4「充分且必要」）。
