# 总览：先建立心智地图

软件工程的所有概念，本质都在回答**两个核心问题**：

```
问题 1：复杂的东西怎么变简单？
   → 模块化、抽象、封装、内聚

问题 2：分开的东西怎么协作？
   → 接口、依赖、耦合、错误边界
```

所有概念围绕这两个问题展开。你只要记住这个心智地图，后面的内容都是它的展开。

类比：你做交易员的工作也是这两个问题——“复杂的市场怎么拆解理解”+“不同部门/系统怎么协作”。**软件工程的智慧本质上和管理工程是同源的**。

---

# 第一章：复杂度管理（怎么让大东西变小）

## 1.1 模块化（Modularity）

### 定义

**把大系统拆成可以独立理解的小块**。每个块（模块）是一个有明确边界的”零件”。

### 类比

- **数学**：一本数学书拆成”集合论”“线性代数”“微积分”几章。每章可以单独学，但又服务于整本书。
- **交易**：一个交易团队拆成”研究”“执行”“风控”“IT”几个组。每组职责清晰，但又共同服务于”赚钱”这个总目标。

### 关键属性

```
✅ 好的模块化：
   - 每个模块职责单一（"这个模块只做 X"）
   - 模块边界清晰（"这件事归 A，不归 B"）
   - 修改一个模块不会影响其他模块

❌ 糟糕的模块化：
   - 一个模块管 10 件事
   - 不知道某个功能"应该写在哪里"
   - 改一行代码，整个系统要重测
```

### 你的项目里的体现

你的项目分成 ExecutionView、CostView、scripts —— **这就是模块化**。每一个是一个模块（更准确说叫”子系统”，但这是模块化的更大粒度）。

### 为什么重要

人脑一次能处理的复杂度有上限（心理学叫”工作记忆”，大概 7±2 个概念）。**模块化让你每次只看一个模块，不用同时记住所有东西**。这不是”软件特殊需要”，是人脑的物理限制。

---

## 1.2 抽象（Abstraction）

### 定义

**忽略细节，只关注”做什么”，不关注”怎么做”**。

### 类比

- **数学**：你说”求导数”，不需要每次都展开极限定义。“导数”是一个抽象，封装了背后的极限运算。
- **交易**：你说”下一个 VWAP 单”，不需要每次都解释 VWAP 算法。“VWAP 单”是一个抽象。
- **生活**：你说”开车去机场”，不需要描述每次踩油门、转方向盘。“开车”是一个抽象。

### 关键属性

抽象是**分层**的：

```
高抽象层：    "我想分析滑点"       ← 业务语言
              ↓
中抽象层：    "运行 TCA pipeline"  ← 系统语言
              ↓
低抽象层：    "调用 attribution.run_metrics(start, end)"  ← 代码语言
              ↓
最低层：      "执行 SQL: SELECT ... FROM fills"  ← 实现语言
```

**好的系统**：每一层只关心相邻层。你在业务层不需要知道 SQL 长什么样。

### 你的项目里的体现

`PipelineFactory.create_attribution()` —— 这是抽象。
- 高抽象用法：`pipeline = PipelineFactory.create_attribution()`，一行搞定
- 它内部装配 stages、配置 context、跑调度——**这些细节被抽象隐藏了**

### 为什么重要

抽象是**人类对抗复杂度的最强武器**。

没有抽象，你写代码每次都要从头解决”如何在硬盘上存数据”这种问题。
有了抽象（数据库），你只关心”存”“取”。

**思考题**：为什么数学里”群、环、域”这些抽象那么有力？因为它们让你不需要每次都重新证明”加法满足结合律”——你证明一次”群有结合律”，所有具体的群都自动满足。**软件抽象的威力同源**。

---

## 1.3 封装（Encapsulation）

### 定义

**把数据和操作数据的方法捆绑在一起，并隐藏内部细节**。

### 类比

- **生活**：你的银行账户。你能调用 `存钱`、`取钱`、`查余额` 这些方法，但不能直接打开银行金库改数字。**你的账户对象封装了余额数据，只暴露受控的方法**。
- **交易**：一个订单对象。你可以调用 `cancel()`、`modify()`，但不能直接修改它的 `status` 字段——必须通过方法。

### 封装 = 抽象 + 保护

抽象关注”对外简化”，封装额外加一层”对内保护”：

```python
# 没封装：暴露细节，谁都能改
class Order:
    pass

order = Order()
order.status = "filled"   # 任何人都能这么改，可能跳过校验
order.quantity = -100      # 负数？没人拦你

# 封装好：内部受保护
class Order:
    def __init__(self):
        self._status = "pending"  # 下划线表示"私有"
        self._quantity = 0

    def fill(self, qty):
        if qty <= 0:
            raise ValueError("qty must be positive")
        self._quantity -= qty
        if self._quantity == 0:
            self._status = "filled"
```

### 关键属性

| 属性 | 含义 |
| --- | --- |
| **私有数据** | 外部无法直接读写（用 `_` 前缀或语言机制） |
| **公共方法** | 外部使用对象的唯一通道 |
| **不变量保护** | 通过方法确保数据始终合法（如订单数量永远 ≥ 0） |

### 为什么重要

如果不封装，**对象的状态可能被任意代码污染**。半年后你 debug 时根本不知道是谁在哪改坏了它。

封装让 bug **可定位**——不变量被破坏了？只可能是少数几个方法干的，不用全代码搜索。

---

## 1.4 内聚（Cohesion）

### 定义

**一个模块内部的元素是否”属于同一件事”**。

### 类比

- **高内聚（好）**：一本书叫《微积分》，所有章节都讲微积分。
- **低内聚（坏）**：一本书叫《微积分》，但里面塞了第 5 章《唐诗三百首》、第 6 章《如何做菜》。

### 怎么识别内聚程度

问这个模块：**“你能用一句话说清楚自己是干什么的吗？”**

```
高内聚：
"我负责把 raw_fills 处理成 processed_fills"
→ 单一、清晰，模块名应该叫 fills_processor

低内聚：
"我负责把 raw_fills 处理成 processed_fills，
 顺便发邮件通知，
 还有计算交易员的奖金，
 偶尔也下载 Bloomberg 数据..."
→ 这是 4 件事，应该拆成 4 个模块
```

### 内聚的等级

```
最高等级（追求）：功能内聚
   - 模块只做一件事
   - 例：fill_aggregator.py 只做聚合

中等：顺序内聚
   - 多件事但有先后关系
   - 例：ingest_and_process（先摄入再处理）
   - 可以接受，但更好是拆开

低：逻辑内聚
   - 几件相似的事被塞一起
   - 例：utils.py 里同时有"日期格式化"和"金额计算"
   - 这是技术债

最低：偶然内聚
   - 完全不相关的代码堆在一起
   - 例：misc.py（杂项）
   - 必须重构
```

### 为什么重要

高内聚的模块**容易理解、容易测试、容易复用**。低内聚的模块是 bug 温床。

**实战准则**：当一个模块的描述里出现”和”“以及”“顺便”——就是低内聚的信号，考虑拆分。

---

# 第二章：协作机制（分开的东西怎么一起干活）

## 2.1 接口（Interface）

### 定义

**模块对外承诺的”使用方式”——别人怎么调用我**。

### 类比

- **生活**：电源插座是一个接口。无论你的电器是手机还是冰箱，只要插头形状对（接口匹配），就能用。**你不需要知道电是怎么发出来的**。
- **交易**：Bloomberg API 是一个接口。你调用 `fetch_bdib()` 拿到数据，**不需要知道 Bloomberg 内部如何存数据**。

### 接口的两个层面

**1. 语法接口**：函数/方法的签名

```python
def fetch_bdib(ticker: str, date: str) -> pd.DataFrame:
    ...
```

这告诉你：传两个字符串，得到一个 DataFrame。

**2. 语义接口**：行为约定（更重要！）

```python
def fetch_bdib(ticker: str, date: str) -> pd.DataFrame:
    """
    获取指定 ticker 在指定日期的 BDIB 数据。

    - ticker 必须是 Bloomberg 格式（如 "AAPL US Equity"）
    - date 必须是 YYYYMMDD 格式
    - 周末/节假日返回空 DataFrame，不抛异常
    - 网络失败时抛 NetworkError
    - 单次调用不超过 5 秒
    """
```

**这些注释里的承诺，就是语义接口**。语法接口编译器能检查，语义接口只能靠文档+测试保证。

### 为什么接口是核心概念

> **整个软件工程的核心智慧就一句话：依赖接口，不依赖实现**。
> 

意思是：当 A 需要用 B 的功能，A **只看 B 的接口**（“我怎么调用你”），**不关心 B 内部怎么实现**。

**好处**：
- B 改了内部实现，A 不受影响（只要接口不变）
- 可以用另一个 B’ 替换 B（只要 B’ 实现了同样的接口）

### 你的项目里的体现

`BaseStage` 是一个抽象接口：

```python
class BaseStage(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: ...

    @abc.abstractmethod
    def process(self, context) -> bool: ...
```

它说：“任何 stage 必须有 name 属性和 process 方法”。这就是**接口契约**。
`FinancialPipeline` 调度时只看这个接口，不关心具体是 IngestStage 还是 BDIBStage。

---

## 2.2 依赖（Dependency）

### 定义

**A 需要 B 才能工作，就说 A 依赖 B**。

### 类比

- 你做饭依赖于菜（没菜做不出饭）
- 一个 Python 文件 `import pandas`，就是依赖 pandas

### 依赖的方向性

依赖**有方向**：

```
A → B  表示 A 依赖 B（B 不知道 A 的存在）
A ↔ B  表示双向依赖（互相需要，麻烦）
```

### 依赖图

整个项目所有依赖画出来就是**依赖图**。

**好的依赖图**：
- 像树（或有向无环图 DAG）：从顶向下，没有循环
- 底层是基础设施（数据库、配置）
- 顶层是业务逻辑

**坏的依赖图**：
- 有循环：A 依赖 B，B 依赖 C，C 依赖 A
- 没有层次：什么都依赖什么，像一团毛线

### 循环依赖（Circular Dependency）

```
模块 A: import B
模块 B: import C
模块 C: import A    ← 循环！
```

**为什么是灾难**：
- 测试 A 时必须先有 B 和 C，但 C 又需要 A 才能跑
- 改 A 可能影响 B、C，C 反过来又影响 A
- Python 真的会因此报 `ImportError`

**实战准则**：**永远不允许循环依赖**。一旦发现，立刻重构（通常是抽出一个共同的下层模块）。

### 你的项目里的体现

你之前给我的 `pipeline.py` 文件顶部：

```python
from .fill_aggregator import generate_agg_fills_10s
from .fill_ingestion import ingest_all_excel_files
from .raw_fills_db import RawFillsDB
```

这些都是依赖。`pipeline.py` 依赖了下层的 6-8 个模块。

---

## 2.3 耦合（Coupling）

### 定义

**模块之间互相牵连的紧密程度**。

### 类比

- **低耦合（好）**：USB 接口。不同厂商的设备都能互换。
- **高耦合（坏）**：苹果早期的接口。换一个手机，所有配件都报废。

### 耦合的等级（从坏到好）

| 等级 | 描述 | 例子 |
| --- | --- | --- |
| **内容耦合**💀 | 一个模块直接修改另一个模块的内部数据 | `module_a._internal_state = new_value` |
| **公共耦合** | 多个模块共享全局变量 | 全局 `config` 字典，谁都能改 |
| **控制耦合** | A 传一个”开关”参数，决定 B 走哪条路径 | `process(data, mode="fast" or "slow")` |
| **数据耦合**✅ | A 给 B 传数据，B 处理数据，仅此而已 | `result = process(data)` |
| **消息耦合**✅✅ | A 完全不知道 B 存在，通过消息中介通信 | 发布/订阅模式 |

**实战准则**：**追求”数据耦合”以下，避免”公共耦合”以上**。

### 高耦合的代价

```python
# 高耦合（坏）：A 模块知道 B 模块的内部结构
class BadProcessor:
    def process(self, db):
        db._cursor.execute("SELECT ...")  # 知道 db 内部有 _cursor
        db._connection.commit()           # 知道有 _connection

# 后果：DB 类内部一改，BadProcessor 立刻挂掉

# 低耦合（好）：A 只用 B 的公共接口
class GoodProcessor:
    def process(self, db):
        result = db.query("SELECT ...")  # 只用公共方法
        db.commit()
```

### 内聚 vs 耦合：黄金法则

**软件工程一句话总结**：

> **High cohesion, low coupling**
（高内聚，低耦合）
> 

意思是：
- 一个模块**内部**：紧密相关（高内聚）
- 模块**之间**：松散连接（低耦合）

这是**整个软件工程最重要的一条法则**。所有其他设计原则都是它的细化。

### 你的项目里的体现

`PipelineContext` 是一个设计良好的低耦合机制：
- 各个 Stage 之间不直接通信
- 都通过 context 传数据
- A stage 改了内部实现，B stage 不受影响（只要 context 字段稳定）

---

## 2.4 错误边界（Error Boundary）

### 定义

**明确划定”哪里负责处理哪种错误”的边界**。

### 类比

- **生活**：消防系统的防火墙。一处着火不会烧到整栋楼。
- **交易**：每个 trader 有 risk limit。一个 trader 爆仓不会让整个 desk 倒闭。
- **代码**：try/except 块就是错误边界。

### 三种处理错误的策略

**策略 1：让它崩**（Let it crash）

```python
def parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y%m%d").date()
    # 输入错误？直接抛 ValueError，让上层处理
```

适用：低层工具函数，不知道业务上下文。

**策略 2：捕获并转换**

```python
def fetch_data(ticker: str):
    try:
        return bloomberg.get(ticker)
    except BloombergError as e:
        # 转换成业务异常
        raise DataFetchError(f"Failed to fetch{ticker}") from e
```

适用：跨层调用，把底层异常翻译成上层能理解的语言。

**策略 3：捕获并恢复**

```python
def process_dates(dates):
    results = []
    for d in dates:
        try:
            results.append(process(d))
        except Exception as e:
            logger.error(f"Failed{d}:{e}")
            # 跳过这一天，继续下一天
    return results
```

适用：批处理，单点失败不应中断整体。

### 错误边界的设计原则

```
✅ 在系统的"自然边界"上设防：
   - 入口（CLI、API endpoint）
   - 跨层调用（业务层 → 数据层）
   - 跨进程调用（HTTP、消息队列）
   - 跨子系统调用

❌ 不要到处 try/except：
   - 每行代码都包 try 是反模式
   - 这表示你不信任任何代码，问题没解决
```

### 你的项目里的体现

```python
class BaseStage(abc.ABC):
    def execute(self, context: PipelineContext) -> bool:
        try:
            return self.process(context)
        except Exception as e:
            context.log_error(self.name, e)
            return False
```

这是一个**完美的错误边界**：
- `BaseStage` 把整个 stage 包成一个错误边界
- 任何 stage 内部的异常都被捕获
- 一个 stage 失败不会导致整个 pipeline 进程崩溃
- 错误被记录到 context 里供后续分析

---

# 第三章：架构韧性（系统怎么活得久）

## 3.1 单一职责原则（Single Responsibility Principle, SRP）

### 定义

**一个模块/类/函数只应该有一个”变化的理由”**。

### 类比

- 一个员工不应该同时是销售、产品经理、财务。一旦公司战略变化，他不知道自己该听谁的。

### 实战识别

```python
# 违反 SRP（坏）
class OrderProcessor:
    def validate(self, order): ...      # 业务逻辑
    def save_to_db(self, order): ...    # 持久化
    def send_email(self, order): ...    # 通知
    def calculate_pnl(self, order): ... # 财务计算
```

这个类有 4 个变化理由：业务规则变、数据库变、邮件系统变、财务规则变。**任何一个变了，这个类都要改**。

```python
# 遵循 SRP（好）
class OrderValidator: ...
class OrderRepository: ...
class OrderNotifier: ...
class PnLCalculator: ...
```

### 为什么重要

- 每个类小、易理解
- 改动影响范围小
- 容易测试

---

## 3.2 开闭原则（Open-Closed Principle, OCP）

### 定义

**对扩展开放，对修改关闭**。

意思是：加新功能时，**新写代码**而不是**改老代码**。

### 类比

- USB 接口设计好后，新设备只要符合 USB 标准就能插上——**不需要改电脑硬件**。

### 你项目里的完美例子

`BaseStage` + `FinancialPipeline` 就是 OCP 的典范：

```python
# 想加一个新 stage？
class SlippageAlertStage(BaseStage):
    def name(self): return "Slippage Alert"
    def process(self, context): ...

# 装配进 pipeline 即可
pipeline.add_stage(SlippageAlertStage())

# FinancialPipeline 一行代码不用改！
```

**对扩展开放**（能加新 stage）+ **对修改关闭**（pipeline 调度逻辑不动）。

### 为什么重要

- 老代码不动 = 老 bug 不会被引入
- 老代码不动 = 老测试不用重跑
- 加功能成本可预测

---

## 3.3 依赖倒置（Dependency Inversion）

### 定义

**高层模块不应该依赖低层模块的具体实现，两者都应该依赖抽象（接口）**。

### 类比

```
坏（直接依赖具体）：
你的灯泡只能用某个特定品牌

好（依赖抽象接口）：
你的灯座符合 E27 标准，任何 E27 灯泡都能装
```

### 代码示例

```python
# 坏：高层逻辑直接依赖低层数据库
class OrderService:
    def save(self, order):
        sqlite_conn = sqlite3.connect("orders.db")  # 写死了 SQLite
        sqlite_conn.execute("INSERT ...")

# 一旦换数据库（PostgreSQL、MongoDB），整个 OrderService 重写

# 好：依赖抽象接口
class OrderRepository(abc.ABC):
    @abc.abstractmethod
    def save(self, order): ...

class SQLiteOrderRepo(OrderRepository):
    def save(self, order): ...

class PostgresOrderRepo(OrderRepository):
    def save(self, order): ...

class OrderService:
    def __init__(self, repo: OrderRepository):  # 接收抽象
        self.repo = repo

    def save(self, order):
        self.repo.save(order)  # 不关心具体是谁

# 换数据库？换一行代码：
service = OrderService(repo=PostgresOrderRepo())
```

### 为什么重要

- **可测试**：测试时传一个 `MockOrderRepo`，不用真连数据库
- **可替换**：换实现不动业务代码
- **解耦**：业务逻辑和基础设施独立演化

### 你的项目里的体现

`PipelineContext` 用类型注解 `Optional[RawFillsDB]`——理论上可以传任何实现了 RawFillsDB 接口的对象。这给了未来替换实现的可能性。

---

## 3.4 关注点分离（Separation of Concerns）

### 定义

**不同性质的逻辑写在不同地方**。

### 常见的关注点分类

```
业务逻辑：     "订单数量必须 > 0"
数据持久化：   "怎么把订单存进数据库"
表现层：       "怎么把订单显示给用户"
基础设施：     "怎么连接 Bloomberg"
配置：         "数据库地址在哪"
日志：         "出错时记录什么"
```

**这 6 类应该写在不同模块里**。

### 实战体现：分层架构

大部分项目都有一种”层”的结构：

```
┌─────────────────────────────┐
│ 表现层（Web/CLI/UI）         │
├─────────────────────────────┤
│ 业务逻辑层（核心规则）        │
├─────────────────────────────┤
│ 数据访问层（数据库/API）      │
├─────────────────────────────┤
│ 基础设施层（日志/配置/网络）   │
└─────────────────────────────┘
```

**规则**：
- 上层可以依赖下层
- 下层不能依赖上层
- 同层之间尽量不依赖

### 你的项目里的体现

CostView 项目隐式有这种分层：

```
入口层：       __main__.py, daily_update.py
业务编排层：   pipeline.py, PipelineFactory
业务逻辑层：   fill_aggregator, order_label, attribution/...
数据访问层：   raw_fills_db, processed_fills_db, ...
基础设施层：   processing_config, secure_config
```

---

# 第四章：质量保障（怎么知道东西没坏）

## 4.1 测试金字塔

```
            ┌───┐
            │E2E│     端到端测试（少）：跑整个系统
          ┌─┴───┴─┐
          │集成测试│   集成测试（中）：多模块协作
        ┌─┴───────┴─┐
        │ 单元测试   │  单元测试（多）：单个函数/类
        └───────────┘
```

### 单元测试（Unit Test）

测试**单个函数或类**，不依赖外部资源（数据库、网络）。

```python
def test_fill_aggregator():
    fills = pd.DataFrame({...})
    result = generate_agg_fills_10s(fills)
    assert len(result) > 0
    assert result['volume'].sum() == fills['volume'].sum()  # 不变量
```

特点：快（毫秒级）、多（成百上千个）、稳定。

### 集成测试

测试**多个模块协作**。可能涉及真数据库（但用测试数据库）。

```python
def test_pipeline_end_to_end():
    ctx = PipelineContext(target_dates=["20260101"])
    pipeline = PipelineFactory.create_daily_e2e_pipeline()
    pipeline.run(ctx)
    assert ctx.is_successful
    assert ctx.summary["processing"]["rows_processed"] > 0
```

特点：慢（秒级）、少、捕获模块协作的 bug。

### E2E 测试（端到端）

模拟**真实用户行为**。

```python
def test_user_can_run_pipeline_via_cli():
    result = subprocess.run(["python", "-m", "src", "--pipeline"])
    assert result.returncode == 0
```

特点：很慢（分钟级）、极少、捕获部署级问题。

### 实战准则

```
70% 单元测试 + 25% 集成测试 + 5% E2E
```

为什么这个比例？
- 单元测试便宜，多写
- E2E 贵且慢，少写
- 集成测试是平衡点

---

## 4.2 不变量（Invariant）

### 定义

**系统在任何时候都必须为真的命题**。

### 类比

- **数学**：欧氏空间中”两点之间直线最短”是不变量。
- **会计**：借方 = 贷方（永远）。
- **交易**：所有头寸的总和 = 总仓位（永远）。

### 软件中的不变量例子

```
账户类的不变量：
- 余额 ≥ 0（不能透支）
- 历史交易总和 = 当前余额

订单类的不变量：
- 已成交数量 ≤ 总数量
- 状态只能在合法状态机里转换

Pipeline 的不变量：
- 聚合后的总成交量 = 原始 fills 总成交量
- 处理过的日期一定有对应的输出表
```

### 怎么用不变量

**1. 写在代码里作为断言**

```python
def fill(self, qty):
    self._filled_qty += qty
    assert self._filled_qty <= self._total_qty, "已成交超过总量！"
```

**2. 写在测试里作为检查**

```python
def test_aggregation_preserves_volume():
    raw = generate_test_fills()
    agg = generate_agg_fills_10s(raw)
    assert raw['volume'].sum() == agg['volume'].sum()
```

### 为什么重要

- **不变量是系统正确性的核心**——所有 bug 本质都是某个不变量被破坏了
- **找 bug 时先找最近被破坏的不变量**，比逐行读代码快 10 倍
- **你的数学训练在这里有先天优势**——你天生擅长找不变量

---

## 4.3 副作用（Side Effects）

### 定义

**函数除了”返回值”以外对外界产生的影响**。

### 类比

```python
# 纯函数（无副作用）：只算东西
def add(a, b):
    return a + b
# 100 次调用结果都一样，对外界没影响

# 有副作用：会动外界状态
def save_order(order):
    db.execute("INSERT ...")  # 改数据库
    send_email(...)           # 发邮件
    logger.info(...)          # 写日志
    return True
```

### 副作用的种类

```
1. 数据库读写
2. 文件读写
3. 网络调用
4. 修改全局变量
5. 改对象的内部状态
6. 打印/日志
7. 抛异常
8. 启动线程/进程
```

### 为什么副作用是重点关注对象

**副作用难测试、难调试、难重现**：
- 纯函数 `add(2, 3)` 永远等于 5
- 有副作用的函数 `save_order(o)`，结果取决于数据库当前状态、网络是否可用、之前调用了多少次……

**实战准则**：
- 尽量让函数纯
- 必须有副作用时，**集中在少数模块里**（比如所有数据库操作放在 `repository` 层）
- 副作用必须**显式**（看函数名/文档就知道有副作用）

### 你的项目里的体现

阶段 2 让 AI 写契约卡片时，我专门要求列”副作用清单”——这就是为什么。**副作用是模块的”危险面”，必须显式记录**。

---

# 第五章：常用工程概念速览

这些概念虽小但常出现，速速过一遍。

## 5.1 配置（Configuration）

**定义**：把会变的参数（路径、阈值、开关）从代码里抽出来。

```python
# 坏：硬编码
def fetch():
    conn = sqlite3.connect("/Users/me/data/fills.db")  # 写死

# 好：从配置读
def fetch():
    conn = sqlite3.connect(Config.DB_PATH)
```

**为什么重要**：换环境（开发/生产）只改配置，不改代码。

---

## 5.2 日志（Logging）

**定义**：在代码运行时记录关键事件，供事后分析。

**关键级别**：

```
DEBUG:    "进入函数 X，参数 Y"（开发时看）
INFO:     "处理了 100 条记录"（正常运行时看）
WARNING:  "数据格式异常，使用默认值"（需要注意）
ERROR:    "操作失败"（需要修复）
CRITICAL: "系统宕机"（紧急）
```

**实战准则**：
- 不要用 `print`，用 `logging` 模块
- INFO 级别记录”做了什么”
- ERROR 级别记录”出了什么问题，包括上下文”

---

## 5.3 异常（Exception）vs 错误码（Error Code）

**异常**（Python/Java 主流）：出错时抛出，沿调用栈往上找处理者。

```python
def divide(a, b):
    if b == 0:
        raise ValueError("除数不能为 0")
    return a / b
```

**错误码**（C/Go 主流）：出错时返回一个特殊值。

```c
int divide(int a, int b, int* result) {
    if (b == 0) return ERROR_DIV_ZERO;
    *result = a / b;
    return SUCCESS;
}
```

**Python 项目用异常**。但要注意：**别滥用异常做正常控制流**——异常只用于”不该发生但发生了”的情况。

---

## 5.4 状态（State）vs 无状态（Stateless）

**有状态**：模块/对象记得过去发生的事。

```python
class Counter:
    def __init__(self):
        self.count = 0  # 状态
    def add(self):
        self.count += 1  # 状态变化
```

**无状态**：不记得任何事，每次调用独立。

```python
def add(a, b):
    return a + b  # 没有持久状态
```

**实战准则**：能无状态尽量无状态，可测试性、可并发性都好得多。

---

## 5.5 同步 vs 异步

**同步**：A 调用 B，A 等 B 完成才继续。

```python
result = fetch_from_bloomberg()  # 等 5 秒
print(result)                     # 然后才执行
```

**异步**：A 发起 B 后立刻继续，B 完成后通知 A。

```python
future = fetch_from_bloomberg_async()
do_other_work()                   # 同时做别的
result = await future             # 需要时再等
```

**实战场景**：
- I/O 密集（网络、数据库）→ 异步收益大
- CPU 密集（计算）→ 异步没用，要多进程

---

## 5.6 幂等性（Idempotency）

**定义**：操作执行 1 次和 N 次结果一样。

```
幂等的：
- 把开关设为 ON（设几次都是 ON）
- DELETE 一个文件（已删除时再删，结果一样）

非幂等的：
- 转账 100 元（执行两次就转了 200）
- 计数器 +1
```

**为什么重要**：网络不稳定时，重试操作必须幂等才安全。

**实战准则**：API 设计时优先做幂等。

---

# 第六章：把所有概念串起来

回到开头说的两个核心问题：

```
问题 1：复杂的东西怎么变简单？
→ 模块化（拆）
→ 抽象（隐藏细节）
→ 封装（保护数据）
→ 内聚（每个模块只做一件事）
→ 单一职责（更细粒度的内聚）

问题 2：分开的东西怎么协作？
→ 接口（约定怎么调用）
→ 依赖（明确谁需要谁）
→ 耦合（连接强度，越低越好）
→ 错误边界（出问题时影响范围可控）
→ 依赖倒置（依赖接口而非实现）
→ 关注点分离（不同性质的代码分开）
→ 开闭原则（加功能不动旧代码）
```

**这就是软件工程的全部基础**。

后面接触的所有概念——MVC、微服务、领域驱动设计、CI/CD、DevOps——**全是这些基础概念在不同场景下的展开**。

---

# 你接下来该怎么用这些概念

## 1. 在你已有的工作中识别它们

回看你的 CostView pipeline.py，你能识别出：
- ✅ **模块化**：每个 Stage 是一个模块
- ✅ **抽象**：BaseStage 是抽象基类
- ✅ **封装**：PipelineContext 封装了共享状态
- ✅ **接口**：BaseStage 定义了 stage 必须实现的接口
- ✅ **依赖倒置**：FinancialPipeline 依赖 BaseStage 抽象，不依赖具体 stage
- ✅ **错误边界**：BaseStage.execute 是边界
- ✅ **开闭原则**：加新 stage 不改 pipeline
- ✅ **关注点分离**：调度 / 业务 / 数据访问分层

**这些都不是巧合**——`pipeline.py` 是一个工程素养很好的设计。能识别这些，你就能复用这种设计到其他地方。

## 2. 在新工作中应用它们

当 agent 给你写代码时，用这些概念**审核**：
- “这个新模块内聚吗？还是塞了几件事？”
- “和现有模块的耦合方式是什么？”
- “副作用都列清楚了吗？”
- “错误边界在哪？”
- “有不变量需要在测试里检查吗？”

**这些问题问出来，agent 的输出质量会立刻提升 50%**——因为它被迫显式地考虑这些。

## 3. 在架构讨论中”听懂”

下次我们讨论时说”这个设计耦合太高了”或”违反了 SRP”——你不再需要查字典。我们能直接进入实质讨论。

---

# 关键纪律：不要陷入”概念崇拜”

最后一个忠告：**这些概念是工具，不是教条**。

我见过的最糟糕的工程师不是不懂概念的，而是**懂概念但僵化套用**的：
- 为了”低耦合”把代码拆得太碎，反而难以理解
- 为了”OCP”造一堆抽象基类，但实际只有一个实现
- 为了”SRP”一个 5 行函数拆成 3 个类

**正确心态**：
- 概念是”识别问题”的工具，不是”必须遵守”的法律
- 当你发现一段代码”难改、难懂、难测”，用这些概念诊断为什么
- 改动时朝”高内聚、低耦合”方向走，但不必追求极致

**判断标准**：**实用主义** > 教条主义。