"""性能热点检测器 — PF-01 ~ PF-06（高耗时 / 高内存候选）。

判定一律为**静态候选**，不代替 profiler：命中项含义是「值得实测的可疑模式」，
报告与 fix_hint 均显式要求用 py-spy / cProfile / tracemalloc / EXPLAIN QUERY PLAN 复核。
"""

from __future__ import annotations

import ast

from scripts.quality_gate.ast_utils import (
    cyclomatic_complexity,
    func_line_count,
    iter_functions,
    make_fingerprint,
    nesting_depth,
    rel_posix,
)
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config

_LOOP_TYPES = (ast.For, ast.AsyncFor, ast.While)
_GROW_METHODS = {"append", "add", "update", "setdefault", "extend", "insert"}


def detect(ctx: ScanContext) -> list[Finding]:
    """PF-01 ~ PF-06（PF-06 全局按热度分取 Top-N）。"""
    findings: list[Finding] = []
    hotspots: list[tuple[float, Finding]] = []
    for path in ctx.python_files:
        if any(part in config.EXEMPT_DIR_PARTS for part in path.parts):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        rel = rel_posix(path, ctx.root)
        text = ctx.text(path) or ""
        findings.extend(_loop_io(tree, rel))
        findings.extend(_nested_loops(tree, rel))
        findings.extend(_full_reads(tree, rel))
        findings.extend(_non_sargable(tree, rel))
        findings.extend(_unbounded_containers(tree, text, rel))
        findings.extend(_loop_str_concat(tree, rel))
        hotspots.extend(_hotspots(tree, text, rel))
    # PF-06 是全局排序产物（Top-N），仅在 full 扫描输出：
    # staged 模式只看得见少数文件，排序失去意义且会污染 full 的基线清偿统计
    if ctx.mode == "full":
        hotspots.sort(key=lambda item: -item[0])
        findings.extend(finding for _, finding in hotspots[:config.HOTSPOT_TOP_N])
    return findings


# ── PF-01 循环内 IO / 查询（N+1）──────────────────────────────────

def _loop_io(tree: ast.Module, rel: str) -> list[Finding]:
    """循环体内出现数据库/文件/HTTP 调用。"""
    findings: list[Finding] = []
    for loop, depth in _iter_loops(tree):
        names = _io_calls_in_executed(loop)
        if not names:
            continue
        severity = Severity.HIGH if depth > config.MAX_LOOP_NESTING else Severity.MEDIUM
        findings.append(_mk(
            "PF-01", rel, loop.lineno, "<loop>", f"loop-io@{loop.lineno}",
            f"循环内 IO/查询（N+1 风险，嵌套层 {depth}）：{', '.join(sorted(names))}",
            "批量化为单次查询/单次请求（SQL `IN (...)`、executemany、批量 API）；"
            "确需逐条时用缓存或并发池，并加 `EXPLAIN QUERY PLAN` 验证",
            severity, 1.5 if severity is Severity.HIGH else 1.0))
    return findings


def _io_calls_in_executed(loop: ast.AST) -> set[str]:
    """循环中**会重复执行**的部分命中的 IO 调用名。

    ``for r in cursor.fetchall():`` 的迭代表达式只在进入循环时求值一次，
    不属于 N+1（逐行 walk 整个循环节点会把它误判为循环内 IO）；
    ``while f():`` 的条件每轮求值，仍需计入。
    """
    parts: list[ast.AST] = list(getattr(loop, "body", []))
    parts.extend(getattr(loop, "orelse", []))
    if isinstance(loop, ast.While):
        parts.append(loop.test)
    names: set[str] = set()
    for node in parts:
        names |= _io_calls_in(node)
    return names


def _io_calls_in(loop: ast.AST) -> set[str]:
    """节点子树内命中的 IO 调用名集合。"""
    names: set[str] = set()
    for node in ast.walk(loop):
        if not isinstance(node, ast.Call):
            continue
        chain, last = _callee_chain(node)
        if not last:
            continue
        if last in config.HARD_IO_CALL_NAMES or (last in config.HTTP_CALL_NAMES
                                                and chain & set(config.HTTP_RECEIVER_HINTS)):
            names.add(last)
    return names


def _callee_chain(call: ast.Call) -> tuple[set[str], str]:
    """调用表达式的（接收者词元集合, 调用名）。"""
    func = call.func
    if isinstance(func, ast.Name):
        return {func.id}, func.id
    parts: list[str] = []
    node: ast.AST = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return set(parts), parts[0] if parts else ""


# ── PF-02 嵌套循环 / 线性扫描 ─────────────────────────────────────

def _nested_loops(tree: ast.Module, rel: str) -> list[Finding]:
    """循环嵌套 ≥2 层，或循环内线性扫描调用。"""
    findings: list[Finding] = []
    for loop, depth in _iter_loops(tree):
        if depth > config.MAX_LOOP_NESTING:
            # 2 层极常见（小集合遍历），判 low；≥3 层复杂度陡增，判 medium
            severity = Severity.LOW if depth == 2 else Severity.MEDIUM
            findings.append(_mk(
                "PF-02", rel, loop.lineno, "<loop>", f"nested-loop@{loop.lineno}",
                f"嵌套循环 O(n²) 风险：循环嵌套 {depth} 层",
                "用 Set/Dict 建索引把内层查找降为 O(1)，或用 numpy/pandas 向量化；"
                "除非内层确为常量级小规模（此时 --suppress 并注明）",
                severity, 1.0 if severity is Severity.MEDIUM else 0.5))
        scan = _linear_scan_in(loop)
        if scan:
            findings.append(_mk(
                "PF-02", rel, loop.lineno, "<loop>", f"linear-scan@{loop.lineno}",
                f"循环内线性扫描：`{scan}` 每轮遍历一次序列",
                "循环外预建 `set`/`dict` 索引后做 O(1) 判定，避免 list.index/count 的 O(n) 扫描",
                Severity.LOW, 0.5))
    return findings


def _linear_scan_in(loop: ast.AST) -> str | None:
    """循环体内命中的线性扫描调用名。"""
    for node in ast.walk(loop):
        if isinstance(node, ast.Call):
            _, last = _callee_chain(node)
            if last in config.LINEAR_SCAN_CALL_NAMES:
                return last
    return None


# ── PF-03 全量加载 / 无界读取 ─────────────────────────────────────

def _full_reads(tree: ast.Module, rel: str) -> list[Finding]:
    """`SELECT *` 无 WHERE/LIMIT 的真无界查询、受约束的未裁剪列、无上限读取调用。

    判定输入是**整条 SQL 文本**：f-string 按拼装后的全文评估（早期版本按单个
    Constant 片段评估，会把 `... LIMIT ? OFFSET ?` 写在另一片段的分页查询误判为无界）。
    """
    findings: list[Finding] = []
    docstrings = _docstring_ids(tree)
    for lineno, sql, assembled in _sql_texts(tree, docstrings):
        finding = _judge_select(lineno, sql, assembled, rel)
        if finding is not None:
            findings.append(finding)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            findings.extend(_judge_full_call(node, rel))
    return findings


def _docstring_ids(tree: ast.Module) -> set[int]:
    """模块/类/函数 docstring 的常量节点 id（文档示例不是可执行查询）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            ids.add(id(first.value))
    return ids


def _sql_texts(tree: ast.Module, docstrings: set[int]) -> list[tuple[int, str, bool]]:
    """提取 (行号, SQL 全文, 是否由拼装得出)。

    纯字面量字符串直接取用；f-string 由各字面量片段拼接、表达式占位为 `?`；
    参与 `+` 拼接的字面量片段标记为拼装（`LIMIT` 可能在另一操作数里）。
    """
    joined_parts = _joined_part_ids(tree)
    concat_parts = _concat_part_ids(tree)
    out: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstrings or id(node) in joined_parts:
                continue
            out.append((node.lineno, node.value, id(node) in concat_parts))
        elif isinstance(node, ast.JoinedStr):
            out.append((node.lineno, _joined_text(node), True))
    return out


def _joined_text(node: ast.JoinedStr) -> str:
    """f-string 拼接后的文本（表达式以 `?` 占位）。"""
    parts: list[str] = []
    for value in node.values:
        parts.append(value.value if isinstance(value, ast.Constant)
                     and isinstance(value.value, str) else "?")
    return "".join(parts)


def _joined_part_ids(tree: ast.Module) -> set[int]:
    """f-string 内部字面量片段的节点 id（由外层 JoinedStr 整体评估，避免片段误判）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            ids |= {id(value) for value in node.values if isinstance(value, ast.Constant)}
    return ids


def _concat_part_ids(tree: ast.Module) -> set[int]:
    """参与 ``+`` 拼接的字符串常量 id（LIMIT/WHERE 可能位于另一操作数）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add)):
            continue
        for operand in (node.left, node.right):
            if isinstance(operand, ast.Constant) and isinstance(operand.value, str):
                ids.add(id(operand))
    return ids


def _judge_select(lineno: int, sql: str, assembled: bool, rel: str) -> Finding | None:
    """单条 SQL 的分级判定（无 WHERE/LIMIT 为 medium，其余为 low；惰性视图不判）。"""
    if not config.RE_SELECT_STAR.search(sql) or config.RE_HAS_LIMIT.search(sql) \
            or config.RE_LAZY_DDL.search(sql):
        return None
    table = _first_table(sql)
    unbounded = not config.RE_HAS_WHERE.search(sql)
    bounded = bool(table) and bool(config.RE_BOUNDED_TABLE_NAME.search(table))
    if unbounded and not bounded and not assembled:
        return _mk("PF-03", rel, lineno, table or "<sql>", f"select-star@{lineno}",
                   f"全量加载：`SELECT *` 无 WHERE / LIMIT 约束（表 `{table or '?'}`），结果集大小不可控",
                   "只 SELECT 需要的列并显式 `LIMIT` / 分页（keyset 分页优先）；"
                   "用 `EXPLAIN QUERY PLAN` 确认索引命中（大表全扫是主要耗时来源）",
                   Severity.MEDIUM, 1.0)
    reason = "SQL 由 f-string 拼装，LIMIT/WHERE 可能由调用方补足，需人工确认" if assembled \
        else ("注册表/标签类小表，行数有界" if bounded else "结果集受 WHERE 约束")
    return _mk("PF-03", rel, lineno, table or "<sql>", f"select-star@{lineno}",
               f"列未裁剪：`SELECT *`（表 `{table or '?'}`；{reason}）",
               "显式列出真正需要的列，让覆盖索引可生效；确认列确实可裁剪后豁免",
               Severity.LOW, 0.5)


def _first_table(sql: str) -> str:
    """SQL 中第一个 FROM 后的表名（小写）。"""
    match = config.RE_SELECT_FROM.search(sql)
    return match.group(1).lower() if match else ""


def _non_sargable(tree: ast.Module, rel: str) -> list[Finding]:
    """WHERE 中对列使用函数 → 索引失效（实测可致千万行全表扫描）。

    证据来源：`raw_fills` 的 `WHERE substr(order_as_of_date, 1, 10) = ?`
    经 `EXPLAIN QUERY PLAN` 确认为 `SCAN raw_fills`（1433 万行），
    而同表的 `WHERE source_date = ?` 为 `SEARCH ... USING INDEX`。
    """
    findings: list[Finding] = []
    docstrings = _docstring_ids(tree)
    for lineno, sql, _ in _sql_texts(tree, docstrings):
        match = config.RE_NON_SARGABLE_WHERE.search(sql)
        if match is None or config.RE_LAZY_DDL.search(sql):
            continue
        table = _first_table(sql)
        findings.append(_mk(
            "PF-09", rel, lineno, table or "<sql>", f"non-sargable@{lineno}",
            f"索引失效：WHERE 中对列使用函数 `{match.group(1)}()`（表 `{table or '?'}`），"
            "该条件无法走列索引",
            "改写为可利用索引的形式：`substr(col, 1, 10) = ?` → `col >= ? AND col < ?`；"
            "`lower(col) = ?` → 建表达式索引或改存规范化列。"
            "用 `EXPLAIN QUERY PLAN` 确认由 SCAN 转为 SEARCH；"
            "若已存在表达式索引则维持原状并豁免",
            Severity.MEDIUM, 1.0))
    return findings


def _judge_full_call(call: ast.Call, rel: str) -> list[Finding]:
    """全量读取调用与 pandas 无上限读取。"""
    _, last = _callee_chain(call)
    if last in config.FULL_READ_CALL_NAMES:
        return [_mk(
            "PF-03", rel, call.lineno, last, f"full-read@{call.lineno}",
            f"全量读取：`{last}()` 一次性载入全部结果（内存风险）",
            "按需分页（LIMIT/OFFSET 或游标逐行）；确为小表则 --suppress 注明",
            Severity.LOW, 0.5)]
    if last in {"read_csv", "read_parquet", "read_sql", "read_sql_query"} \
            and not _has_any_kwarg(call, {"nrows", "chunksize", "iterator"}):
        return [_mk(
            "PF-03", rel, call.lineno, last, f"pandas-full@{call.lineno}",
            f"全量加载：`{last}()` 未指定 nrows/chunksize，整表进内存",
            "加 `chunksize=` 分块处理，或先下推过滤条件到 SQL 层减少数据量",
            Severity.LOW, 0.5)]
    return []


def _has_any_kwarg(call: ast.Call, names: set[str]) -> bool:
    """调用是否包含任一关键字参数。"""
    return any(kw.arg in names for kw in call.keywords if kw.arg)


# ── PF-04 只增不减的累积容器 ─────────────────────────────────────

def _unbounded_containers(tree: ast.Module, text: str, rel: str) -> list[Finding]:
    """运行时增长且无淘汰证据的模块/类级容器。"""
    findings: list[Finding] = []
    for name, node in _container_defs(tree).items():
        if config.RE_BOUNDED_CONTAINER_NAME.search(name):
            continue                                  # 注册表类：条目数有界
        if not _grows_in_function(tree, name) or config.evict_pattern(name).search(text):
            continue
        findings.append(_mk(
            "PF-04", rel, node.lineno, name, name,
            f"累积容器无淘汰证据：`{name}` 在函数中增长，模块内未见 pop/clear/上限判定",
            "确认是否长生命周期（进程级缓存/长连接会话）：加 maxsize + LRU/FIFO 淘汰，"
            "或改用 `functools.lru_cache(maxsize=)` / `deque(maxlen=)`；短生命周期则 --suppress",
            Severity.MEDIUM, 1.0))
    return findings


def _container_defs(tree: ast.Module) -> dict[str, ast.stmt]:
    """模块级/类级的容器初始化赋值（空字面量或 dict()/list() 等）。"""
    out: dict[str, ast.stmt] = {}
    roots: list[ast.stmt] = [*tree.body]
    roots.extend(node for node in ast.walk(tree) if isinstance(node, ast.ClassDef))
    for root in roots:
        body = root.body if isinstance(root, ast.ClassDef) else [root]
        for stmt in body:
            name = _container_target(stmt)
            if name:
                out.setdefault(name, stmt)
    return out


def _container_target(stmt: ast.stmt) -> str | None:
    """语句是否为容器初始化赋值，返回容器名。"""
    target = stmt.targets[0] if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 else None
    if isinstance(stmt, ast.AnnAssign):
        target = stmt.target
    if not isinstance(target, ast.Name):
        return None
    value = getattr(stmt, "value", None)
    if isinstance(value, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp)):
        return target.id
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) \
            and value.func.id in config.CONTAINER_INIT_NAMES:
        return target.id
    return None


def _grows_in_function(tree: ast.Module, name: str) -> bool:
    """容器是否在函数体内以「数据驱动」方式增长（import 期一次性填充不算）。

    常量键的写入（如 ``REGISTRY["default"] = impl``）条目数由字面量个数决定，
    天然有界，不作为无界累积证据。
    """
    for func in iter_functions(tree):
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and _is_grow_call(node, name):
                return True
            if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Store) \
                    and isinstance(node.value, ast.Name) and node.value.id == name \
                    and not isinstance(node.slice, ast.Constant):
                return True
    return False


def _is_grow_call(node: ast.Call, name: str) -> bool:
    """是否为对该容器的增长调用（常量参数视为有界写入）。"""
    if not isinstance(node.func, ast.Attribute) or node.func.attr not in _GROW_METHODS:
        return False
    if not isinstance(node.func.value, ast.Name) or node.func.value.id != name:
        return False
    return not all(isinstance(arg, ast.Constant) for arg in node.args) or not node.args


# ── PF-05 循环内字符串拼接 ────────────────────────────────────────

def _loop_str_concat(tree: ast.Module, rel: str) -> list[Finding]:
    """循环体内对字符串做 `+=`（O(n²) 复制）。"""
    findings: list[Finding] = []
    for func in iter_functions(tree):
        str_names = _str_assigned_names(func)
        for loop, _ in _iter_loops(func):
            if _has_str_concat(loop, str_names):
                findings.append(_mk(
                    "PF-05", rel, loop.lineno, "<loop>", f"str-concat@{loop.lineno}",
                    "循环内字符串拼接 `+=`：每轮重新分配整串（O(n²) 内存拷贝）",
                    "改为累积 `list` 后 `''.join(parts)`；大文本改用 io.StringIO",
                    Severity.LOW, 0.5))
    return findings


def _str_assigned_names(func: ast.AST) -> set[str]:
    """函数内被赋过字符串常量的变量名。"""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            names.add(node.targets[0].id)
    return names


def _has_str_concat(loop: ast.AST, str_names: set[str]) -> bool:
    """循环体内是否存在字符串 `+=`。"""
    for node in ast.walk(loop):
        if not isinstance(node, ast.AugAssign) or not isinstance(node.op, ast.Add):
            continue
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return True
        if isinstance(node.target, ast.Name) and node.target.id in str_names:
            return True
    return False


# ── PF-06 热点候选（需 profiler 实测）────────────────────────────

def _hotspots(tree: ast.Module, text: str, rel: str) -> list[tuple[float, Finding]]:
    """函数级热度候选（行数 × 嵌套 × 复杂度 × 循环数）+ 文件级超长提示。"""
    out: list[tuple[float, Finding]] = []
    for func in iter_functions(tree):
        score = _hot_score(func)
        if score < config.HOTSPOT_MIN_SCORE:
            continue
        loops = sum(1 for _ in _iter_loops(func))
        out.append((score, _mk(
            "PF-06", rel, func.lineno, func.name, func.name,
            f"热点候选：`{func.name}` 行数 {func_line_count(func)} / 嵌套 "
            f"{nesting_depth(func.body)} / CC {cyclomatic_complexity(func)} / 循环 {loops}"
            f"（热度分 {round(score, 1)}）",
            "非缺陷，仅为实测优先级排序：用 `python -m cProfile` / `py-spy record` / "
            "`tracemalloc` 复核后，再决定拆分函数、加缓存或改算法",
            Severity.LOW, 0.5)))
    line_count = len(text.splitlines())
    if line_count > config.MAX_FILE_LINES:
        out.append((float(line_count), _mk(
            "PF-06", rel, 1, "<file>", "file-hot",
            f"超长文件：{line_count} 行 > {config.MAX_FILE_LINES} 行（维护与冷启动成本高）",
            "按职责拆分为子模块；若同时是热点，优先对象（改一处编译/加载成本都更低）",
            Severity.LOW, 1.0)))
    return out


def _hot_score(func: ast.AST) -> float:
    """热度分：行数 × (1 + 嵌套/2 + CC/10 + 循环数)。"""
    loops = sum(1 for _ in _iter_loops(func))
    return func_line_count(func) * (
        1 + nesting_depth(func.body) / 2
        + cyclomatic_complexity(func) / 10
        + loops
    )


# ── 公共 ─────────────────────────────────────────────────────────

def _iter_loops(node: ast.AST, depth: int = 0):
    """递归产出 (循环节点, 嵌套层数)，最外层循环 depth=1。"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _LOOP_TYPES):
            yield child, depth + 1
            yield from _iter_loops(child, depth + 1)
        else:
            yield from _iter_loops(child, depth)


def _mk(rule_id: str, rel: str, line: int, symbol: str, key: str, message: str,
        fix_hint: str, severity: Severity, effort: float) -> Finding:
    """构造 PF Finding（key 为指纹稳定段）。"""
    return Finding(
        rule_id=rule_id,
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=line,
        symbol=symbol,
        message=message,
        fix_hint=fix_hint,
        fingerprint=make_fingerprint(rule_id, rel, key),
        est_effort_h=effort,
    )
