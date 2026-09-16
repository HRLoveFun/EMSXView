"""清理门禁配置 — 扫描范围 / 阈值 / 豁免清单（唯一真相源，调优只改本文件）。"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.quality_gate.ast_utils import find_project_root
from scripts.quality_gate.config import GLOBAL_EXCLUDE_DIRS

# 项目根（.emsxview-root marker，AP-16 单一信息源）
PROJECT_ROOT: Path = find_project_root(Path(__file__))

# ── 扫描范围 ──────────────────────────────────────────────────────
# 比 quality_gate 更宽：补入 data_access / scripts（清理视角需覆盖全部自有代码）
PYTHON_SCAN_ROOTS: list[str] = [
    "backend",
    "data_access",
    "CostView/src",
    "platform_data",
    "MarketView",
    "scripts",
]
# 前端源码扫描根（可多根）：模块可独立为仓库根级目录（如 ExecutionView/）
FRONTEND_SCAN_ROOTS: list[str] = [
    "frontend/src",
    "ExecutionView/module",
]

# 「零引用」计数的语料排除目录（文档/历史记录不是消费者，计入会掩蔽真死代码）
CORPUS_EXCLUDE_PARTS: set[str] = {"docs", "specs", "plans"} | GLOBAL_EXCLUDE_DIRS
# 判定豁免目录（测试与框架钩子密集，静态判定误报率高）
EXEMPT_DIR_PARTS: set[str] = {"tests", "test"} | GLOBAL_EXCLUDE_DIRS

# ── 规则标题（报告分组 / 终端输出用）──────────────────────────────
RULE_TITLES: dict[str, str] = {
    "CL-01": "冗余文件（import 图零引用）",
    "CL-02": "过时符号（零引用函数/类/常量）",
    "CL-03": "无用逻辑：不可达代码",
    "CL-04": "无用逻辑：恒定条件/等价分支",
    "CL-05": "无用逻辑：空实现存根",
    "CL-06": "冗余逻辑：未使用局部变量赋值",
    "CL-07": "冗余文件：临时/调试遗留",
    "CL-08": "冗余文件：空壳模块",
    "CL-09": "冗余逻辑：注释掉的代码块",
    "CL-10": "冗余文件：前端不可达文件",
    "CL-12": "过时类方法（零引用）",
    "PF-01": "高耗时：循环内 IO/查询（N+1）",
    "PF-02": "高耗时：嵌套循环 O(n²) / 线性扫描",
    "PF-03": "高内存：全量加载 / 无界读取",
    "PF-04": "高内存：只增不减的累积容器",
    "PF-05": "高耗时：循环内字符串拼接",
    "PF-06": "热点候选（需 profiler 实测）",
    "PF-07": "高耗时：前端渲染热点",
    "PF-08": "高耗时：Context Provider 未 memo 化",
    "PF-09": "高耗时：WHERE 列被函数包裹导致索引失效",
}

# ── CL-01 冗余文件（包装 OE-01 算法，扫描范围更宽）────────────────
# 人工审定的豁免清单（posix 相对路径）：静态零引用但有明确归属的保留项
DEAD_FILE_EXEMPT: set[str] = {
    # ADR-0013 声明的「规划中、尚未接线」的平台数据契约（5 个 ABC + DataAccessFactory）：
    # 其实现（CostViewAnalyticsAdapter / build_platform_data_access 等）尚未落地，
    # 删除会与 ADR-0013 及 CODEBUDDY.md 的规划声明冲突 —— 待实现落地后重新评估。
    "platform_data/contracts/data_access.py",
}

# ── CL-02 过时符号 ────────────────────────────────────────────────
# 框架入口 / 约定命名（静态零引用但由框架调用）
DEAD_SYMBOL_EXEMPT_NAMES: set[str] = {
    "main", "lifespan", "handler", "wrapper", "decorator", "setup", "teardown",
    "create_app", "get_settings", "pytest_configure", "pytest_collection_modifyitems",
}
DEAD_SYMBOL_EXEMPT_DECORATORS: set[str] = {
    "abstractmethod", "overload", "fixture", "property", "cached_property",
    "validator", "field_validator", "model_validator", "root_validator",
    "computed_field", "on_event", "middleware", "command", "task",
    "callback_query_handler", "exception_handler", "lru_cache", "cache", "contextmanager",
}
# Web 框架路由装饰器的「方法名」侧特征（@router.get / @app.websocket ...）
ROUTE_DECORATOR_METHODS: set[str] = {
    "get", "post", "put", "patch", "delete", "head", "options",
    "websocket", "websocket_route", "route", "api_route", "include_router",
}
# Web 框架路由装饰器的「接收者」侧特征（@router.* / @app.* / @bp.*）
ROUTE_DECORATOR_TOKENS: set[str] = {
    "router", "app", "ws_router", "api_router", "blueprint", "bp",
}
# CLI 入口文件名/后缀（人工调用即入口，非死代码）
CLI_ENTRY_NAMES: set[str] = {"cli", "manage", "__main__"}
CLI_ENTRY_SUFFIXES: tuple[str, ...] = ("_cli",)
DEAD_SYMBOL_MEDIUM_LOC: int = 10     # 符号长度 ≥ 该值 → medium，否则 low
DEAD_SYMBOL_MIN_NAME_LEN: int = 3    # 常量名长度下限（排除 a/b 之类）

# ── CL-03..CL-09 无用/冗余逻辑 ────────────────────────────────────
COMMENTED_CODE_MIN_LINES: int = 4    # CL-09 连续注释行数下限
COMMENTED_CODE_MIN_HITS: int = 2     # 连续块内至少命中的「语句特征」行数
COMMENTED_CODE_EXEMPT_PARTS: set[str] = {"deploy"}
UNUSED_LOCAL_EXEMPT: set[str] = {"args", "kwargs", "self", "cls", "exc", "err"}
EMPTY_STUB_EXEMPT_DECORATORS: set[str] = {
    "abstractmethod", "overload", "fixture", "setter", "getter", "deleter",
    "property", "cached_property", "staticmethod", "classmethod",
    "validator", "field_validator", "model_validator", "root_validator",
    "computed_field", "on_event", "middleware", "command", "task",
    "hookimpl", "hookspec", "api_route",
}
EMPTY_STUB_PLACEHOLDER_HINTS: tuple[str, ...] = (
    "占位", "预留", "TODO", "placeholder", "not implemented", "no-op", "noop",
)
# 桩/替身代码目录特征（第三方 API 桩天然由空实现组成，不判定）
EMPTY_STUB_EXEMPT_PATH_PARTS: tuple[str, ...] = ("stub", "mock", "fake", "fixture")

# ── CL-07 临时/调试遗留文件命名特征 ───────────────────────────────
# 一律要求下划线前缀/后缀等强特征，避免误伤 debug_utils / check_status 这类正常模块名
TEMP_FILE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^_tmp[_-]|^tmp_|^_scratch"), "临时脚本命名（_tmp_/tmp_/_scratch）"),
    (re.compile(r"^_(?:debug|verify|dump|probe|inspect)\b|^_(?:debug|verify|dump|probe|inspect)_"),
     "一次性调试脚本命名（_debug_/_verify_/_dump_）"),
    (re.compile(r"^_check_|^_test_(?:tmp|scratch)"), "一次性校验脚本命名（_check_）"),
    (re.compile(r"(_old|_copy|_bak|_backup)$"), "遗留副本命名（_old/_copy/_bak）"),
    (re.compile(r"^untitled|^new_file|^temp_"), "编辑器默认命名（untitled/temp_）"),
)

# ── CL-10 前端不可达文件 ──────────────────────────────────────────
# 前端图入口：多入口构建（主应用 + standalone 模块）+ 测试装配
FRONTEND_ENTRY_NAMES: set[str] = {"main.tsx", "main.ts", "index.tsx", "test-setup.ts"}

# ── CL-12 类方法零引用 ────────────────────────────────────────────
# 框架/多态基类：方法由框架按名分派或为契约本身，静态不可证伪 → 整类豁免
CLASS_METHOD_EXEMPT_BASES: set[str] = {
    "Protocol", "ABC", "ABCMeta", "BaseModel", "BaseSettings", "Enum", "StrEnum",
    "IntEnum", "TypedDict", "NamedTuple", "Generic", "Exception", "BaseException",
    "TestCase", "NodeVisitor", "NodeTransformer", "Action", "Handler", "Formatter",
    "BaseHTTPRequestHandler", "Iterator", "Iterable", "Mapping", "Sequence",
}
# 动态名字访问调用名：类体内出现即放弃该类的静态判定（属性可能被运行时装载）
CLASS_METHOD_DYNAMIC_CALLS: set[str] = {
    "getattr", "setattr", "delattr", "vars", "locals", "globals", "eval", "exec",
    "import_module", "__import__",
}
# 类体内定义这些 dunder 说明属性可能由代理/兜底逻辑提供 → 整类豁免
CLASS_METHOD_DYNAMIC_DUNDERS: set[str] = {"__getattr__", "__getattribute__"}
# 桩/替身代码路径特征（第三方 API 桩天然由「零引用」方法组成）
CLASS_METHOD_STUB_PATH_PARTS: tuple[str, ...] = ("stub", "mock", "fake", "fixture")
DEAD_METHOD_MEDIUM_LOC: int = 10     # 方法长度 ≥ 该值 → medium，否则 low
# 人工审定的方法级豁免（契约声明的对外 API —— 零静态调用方不等于可删）
# 依据：.codebuddy/rules/module-boundary.md §2.3 「外部可见方法」列表
# （handoff 适配器的 clear_* 属跨域公开面，删除会破坏已文档化的适配器契约）
DEAD_METHOD_EXEMPT_NAMES: set[str] = {
    "clear_market_to_execution",
    "clear_cost_to_execution",
}

# ── PF 阈值 ───────────────────────────────────────────────────────
MAX_FILE_LINES: int = 800            # 文件级热点阈值
MAX_LOOP_NESTING: int = 1            # 循环嵌套层数上限（> 该值判 O(n²)）
HOTSPOT_TOP_N: int = 15              # PF-06 热点候选输出条数
HOTSPOT_MIN_SCORE: float = 60.0      # 热度分下限（低于此不输出）
# 循环体内必判为 IO 的调用名（数据库 / 文件 / 批处理）
HARD_IO_CALL_NAMES: set[str] = {
    "execute", "executemany", "executescript", "fetchone", "fetchall", "fetchmany",
    "read_sql", "read_sql_query", "to_sql", "read_csv", "read_parquet", "read_excel",
    "commit", "flush",
}
# 循环体内 HTTP 类调用名（需接收者名字命中提示词才判定，避免 dict.get 误报）
HTTP_CALL_NAMES: set[str] = {"get", "post", "put", "patch", "delete", "request", "send"}
HTTP_RECEIVER_HINTS: tuple[str, ...] = (
    "client", "session", "requests", "httpx", "http", "api", "url", "resp", "endpoint",
)
# 线性扫描调用名（循环内命中判 O(n) 扫描）
LINEAR_SCAN_CALL_NAMES: set[str] = {"index"}
# 全量读取调用名（无分页/无上限）
FULL_READ_CALL_NAMES: set[str] = {"readlines", "fetchall"}
# SQL 全量读取特征（供 PF-03 判定）
RE_SELECT_STAR = re.compile(r"select\s+\*\s+from", re.IGNORECASE)
RE_HAS_LIMIT = re.compile(r"\blimit\b", re.IGNORECASE)
RE_HAS_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)
RE_SELECT_FROM = re.compile(r"\bfrom\s+([A-Za-z_]\w*)", re.IGNORECASE)
# 注册表/标签类表：行数由业务主体数量（而非数据量）决定，全读可接受
RE_BOUNDED_TABLE_NAME = re.compile(r"registry|_label$|_mapping$|catalog", re.IGNORECASE)
# 惰性 DDL：`CREATE [OR REPLACE] [TEMP] VIEW ... AS SELECT` 只是视图定义，不加载数据
RE_LAZY_DDL = re.compile(r"create\s+(?:or\s+replace\s+)?(?:temp\s+)?view", re.IGNORECASE)
# 不可 sargable 的 WHERE：对列使用函数会令索引失效（实测 raw_fills 因此 SCAN 1433 万行）
RE_NON_SARGABLE_WHERE = re.compile(
    r"where\b[^;]*?\b(substr|lower|upper|strftime|date|datetime|cast|length|trim|printf|replace)\s*\(",
    re.IGNORECASE,
)

# ── PF-04 累积容器 ────────────────────────────────────────────────
CONTAINER_INIT_NAMES: set[str] = {"dict", "list", "set", "defaultdict", "OrderedDict", "deque"}
# 注册表类命名：条目数由「实现数量」而非「数据量」决定，天然有界，不判无界累积
RE_BOUNDED_CONTAINER_NAME = re.compile(r"registry|impls?|factor(?:y|ies)|singleton", re.IGNORECASE)
# 淘汰/有界证据正则（命中任一即视为有界；刻意不把「重置赋值」算作有界证据）
_EVICT_TEMPLATE: str = (
    r"(?:{name}\s*\.\s*(?:pop|clear|popleft|popitem)\(|del\s+{name}|"
    r"len\(\s*{name}\s*\)\s*[<>]=?|maxlen\s*=|maxsize\s*=)"
)

# ── PF-07/08 前端性能 ─────────────────────────────────────────────
RE_KEY_BY_INDEX = re.compile(r"key=\{\s*(?:index|i|idx|key|rowIndex)\s*\}")
RE_INLINE_PROP = re.compile(r"=\{\{|=\{\s*\(\s*\)\s*=>")
RE_MAP_CALL = re.compile(r"\.map\s*\(")
# 支持 `X.Provider` / 跨行 props（prop 列表用 [^>]*? 匹配换行）
RE_PROVIDER_INLINE_VALUE = re.compile(r"<((?:\w+\.)*\w*Provider)\b[^>]*?value=\{\{")

# ── 门禁模式 ──────────────────────────────────────────────────────
# 默认建议性（不阻断）：删除决策需人工确认，机器不代替人下删库指令
STRICT_ENFORCEMENT: bool = False

# ── 产出路径 ──────────────────────────────────────────────────────
REPORT_DIR: Path = PROJECT_ROOT / "scripts" / "reports" / "cleanup"
DB_PATH: Path = REPORT_DIR / "cleanup.db"

__all__ = ["PROJECT_ROOT", "evict_pattern"]


def evict_pattern(name: str) -> re.Pattern[str]:
    """生成「有界/淘汰证据」正则（按容器名格式化）。"""
    return re.compile(_EVICT_TEMPLATE.format(name=re.escape(name)))
