"""逻辑级清理检测器 — CL-03 / CL-04 / CL-05 / CL-06 / CL-09。

- CL-03 不可达代码：终结语句（return/raise/continue/break）之后仍有同层语句
- CL-04 恒定条件 / 等价分支：``if <常量>``、``while False``、if/else 体完全相同
- CL-05 空实现存根：函数体仅 pass / ... / return None
- CL-06 未使用局部变量赋值：赋值后在同函数内从未被读取
- CL-09 注释掉的代码块：连续注释中命中多条语句特征
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from scripts.quality_gate.ast_utils import iter_functions, make_fingerprint, rel_posix
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config
from ..names import decorator_tokens, is_framework_decorated

# CL-03：同层语句体中的终结语句
_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)
# CL-06：动态访问语义——命中即放弃该函数的未使用变量判定
_DYNAMIC_NAMES = {"locals", "globals", "eval", "exec", "setattr", "getattr", "vars"}
# CL-09：注释行是否「像代码」
_CODE_HINT = re.compile(
    r"^\s*#\s*(?:def\s|class\s|return\b|raise\b|import\s|from\s|if\s|elif\s|else\s*:"
    r"|for\s|while\s|try\s*:|except\b|with\s|print\s*\(|break\b|continue\b"
    r"|[A-Za-z_]\w*\s*=[^=]|[A-Za-z_][\w.]*\s*\([^)]*\)\s*$|[{};]\s*$)"
)


def detect(ctx: ScanContext) -> list[Finding]:
    """CL-03 + CL-04 + CL-05 + CL-06 + CL-09。"""
    findings: list[Finding] = []
    for path in ctx.python_files:
        if any(part in config.EXEMPT_DIR_PARTS for part in path.parts):
            continue
        rel = rel_posix(path, ctx.root)
        tree = ctx.tree(path)
        if tree is not None:
            findings.extend(_unreachable(tree, rel))
            findings.extend(_const_conditions(tree, rel))
            findings.extend(_empty_stubs(tree, rel, path))
            findings.extend(_unused_locals(tree, rel))
        text = ctx.text(path)
        if text is not None:
            findings.extend(_commented_code(text, rel, path))
    return findings


# ── CL-03 不可达代码 ──────────────────────────────────────────────

def _unreachable(tree: ast.Module, rel: str) -> list[Finding]:
    """终结语句之后的同层语句。"""
    findings: list[Finding] = []
    seen: set[int] = set()
    for node in ast.walk(tree):
        for body in _bodies_of(node):
            for index, stmt in enumerate(body[:-1]):
                if not isinstance(stmt, _TERMINATORS) or body[index + 1].lineno in seen:
                    continue
                nxt = body[index + 1]
                seen.add(nxt.lineno)
                findings.append(_mk("CL-03", rel, nxt.lineno, _owner(node),
                                    f"unreachable@{nxt.lineno}",
                                    f"不可达代码：`{type(stmt).__name__.lower()}` 之后仍有同层语句",
                                    "删除不可达语句；若为调试残留请清理，若为防御性兜底请调整控制流",
                                    Severity.MEDIUM, 0.25))
    return findings


def _bodies_of(node: ast.AST) -> list[list[ast.stmt]]:
    """节点持有的语句体列表（body / orelse / finalbody）。"""
    bodies: list[list[ast.stmt]] = []
    for field in ("body", "orelse", "finalbody"):
        value = getattr(node, field, None)
        if isinstance(value, list) and value and all(isinstance(s, ast.stmt) for s in value):
            bodies.append(value)
    return bodies


def _owner(node: ast.AST) -> str:
    """语句体的拥有者符号名。"""
    return getattr(node, "name", type(node).__name__)


# ── CL-04 恒定条件 / 等价分支 ─────────────────────────────────────

def _const_conditions(tree: ast.Module, rel: str) -> list[Finding]:
    """常量条件与等价 if/else 分支。"""
    findings: list[Finding] = []
    for node in ast.walk(tree):
        findings.extend(_judge_condition(node, rel))
    return findings


def _judge_condition(node: ast.AST, rel: str) -> list[Finding]:
    """单个条件节点的判定。"""
    if isinstance(node, (ast.If, ast.IfExp)) and isinstance(node.test, ast.Constant):
        return [_mk("CL-04", rel, node.lineno, "<condition>",
                    f"const-if@{node.lineno}",
                    f"恒定条件：`{type(node).__name__}` 判定值为常量 "
                    f"`{node.test.value!r}`，其中一个分支永不执行",
                    "删除死分支或改为显式开关（配置项/特性标志）",
                    Severity.MEDIUM, 0.25)]
    if isinstance(node, ast.While) and isinstance(node.test, ast.Constant) and not node.test.value:
        return [_mk("CL-04", rel, node.lineno, "<condition>",
                    f"const-while@{node.lineno}",
                    "恒定条件：`while False/0` 循环体永不执行",
                    "删除该死循环；若为临时开关请移除",
                    Severity.MEDIUM, 0.25)]
    if isinstance(node, ast.If) and _same_body(node.body, node.orelse):
        return [_mk("CL-04", rel, node.lineno, "<condition>",
                    f"same-branch@{node.lineno}",
                    "等价分支：`if` 与 `else` 语句体完全相同，条件判定无效果",
                    "删除条件与冗余分支，仅保留一份逻辑",
                    Severity.LOW, 0.25)]
    return []


def _same_body(left: list[ast.stmt], right: list[ast.stmt]) -> bool:
    """两个语句体是否结构等价（用于识别无效果条件）。"""
    if not left or not right:
        return False
    return ast.dump(ast.Module(body=left, type_ignores=[])) == \
        ast.dump(ast.Module(body=right, type_ignores=[]))


# ── CL-05 空实现存根 ──────────────────────────────────────────────

def _empty_stubs(tree: ast.Module, rel: str, path: Path) -> list[Finding]:
    """函数体仅占位语句的存根。"""
    if _is_stub_tree(path):
        return []
    protocol_ids = _protocol_func_ids(tree)
    findings: list[Finding] = []
    for func in iter_functions(tree):
        if id(func) in protocol_ids or not _is_empty_body(_strip_docstring(func.body)):
            continue
        if _skip_stub(func):
            continue
        findings.append(_mk("CL-05", rel, func.lineno, func.name, func.name,
                            f"空实现存根：`{func.name}` 仅含占位语句，无实际行为",
                            "确认无调用方后删除；若为接口占位请补实现或标注 `# TODO(负责人, 日期)`",
                            Severity.LOW, 0.25))
    return findings


def _skip_stub(func: ast.stmt) -> bool:
    """空存根豁免：dunder / 框架装饰器 / docstring 声明为占位。"""
    name = getattr(func, "name", "")
    if name.startswith("__") and name.endswith("__"):
        return True
    tokens = decorator_tokens(func)
    if is_framework_decorated(tokens) or tokens & config.EMPTY_STUB_EXEMPT_DECORATORS:
        return True
    docstring = ast.get_docstring(func) or ""
    return any(hint in docstring for hint in config.EMPTY_STUB_PLACEHOLDER_HINTS)


def _strip_docstring(body: list[ast.stmt]) -> list[ast.stmt]:
    """去掉函数体首行的 docstring。"""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _is_empty_body(body: list[ast.stmt]) -> bool:
    """是否仅为 pass / ... / return None。"""
    if not body:
        return True
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                and stmt.value.value is Ellipsis:
            continue
        if isinstance(stmt, ast.Return) and (stmt.value is None or
                                            (isinstance(stmt.value, ast.Constant)
                                             and stmt.value.value is None)):
            continue
        return False
    return True


def _is_stub_tree(path: Path) -> bool:
    """路径是否位于桩/替身代码目录（第三方 API 桩天然由空实现组成）。"""
    parts = [part.lower() for part in path.parts]
    return any(hint in part for part in parts for hint in config.EMPTY_STUB_EXEMPT_PATH_PARTS)


def _protocol_func_ids(tree: ast.Module) -> set[int]:
    """Protocol / 抽象基类内的方法（空实现是契约本身，不判定）。"""
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
                 for b in node.bases}
        if not (bases & {"Protocol", "ABC", "ABCMeta", "BaseModel"}):
            continue
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                ids.add(id(child))
    return ids


# ── CL-06 未使用局部变量赋值 ─────────────────────────────────────

def _unused_locals(tree: ast.Module, rel: str) -> list[Finding]:
    """赋值后从未被读取的局部变量。"""
    findings: list[Finding] = []
    for func in iter_functions(tree):
        if _has_dynamic_access(func):
            continue
        assigned = _simple_assignments(func)
        used = _loaded_names(func)
        for name, node in assigned.items():
            if name in used or name in config.UNUSED_LOCAL_EXEMPT or name.startswith("_"):
                continue
            findings.append(_mk("CL-06", rel, node.lineno, getattr(func, "name", ""),
                                f"{getattr(func, 'name', '')}.{name}",
                                f"未使用赋值：局部变量 `{name}` 赋值后从未被读取",
                                "删除该赋值（可能顺带删除只为其计算的调用）；"
                                "确实需要保留副作用则改为裸调用并加注释",
                                Severity.LOW, 0.25))
    return findings


def _has_dynamic_access(func: ast.AST) -> bool:
    """是否存在动态名字访问（决定性放弃静态判定）。"""
    for node in ast.walk(func):
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in _DYNAMIC_NAMES:
            return True
    return False


def _simple_assignments(func: ast.AST) -> dict[str, ast.stmt]:
    """单名目标的赋值（含 AnnAssign）；循环/with/except/walrus 目标不计入。"""
    out: dict[str, ast.stmt] = {}
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            out.setdefault(node.targets[0].id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.setdefault(node.target.id, node)
    return out


def _loaded_names(func: ast.AST) -> set[str]:
    """函数内被读取的名字 + 非赋值型绑定名（循环/with/except/walrus，视为已使用）。"""
    names: set[str] = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                names.add(node.id)
            elif not isinstance(node.ctx, ast.Store):
                names.add(node.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


# ── CL-09 注释掉的代码块 ──────────────────────────────────────────

def _commented_code(text: str, rel: str, path: Path) -> list[Finding]:
    """连续注释中命中多条语句特征的代码块。"""
    if any(part in config.COMMENTED_CODE_EXEMPT_PARTS for part in path.parts):
        return []
    lines = text.splitlines()
    findings: list[Finding] = []
    index = 0
    while index < len(lines):
        if not lines[index].lstrip().startswith("#"):
            index += 1
            continue
        end = index
        while end < len(lines) and lines[end].lstrip().startswith("#"):
            end += 1
        block = lines[index:end]
        if len(block) >= config.COMMENTED_CODE_MIN_LINES \
                and _code_hits(block) >= config.COMMENTED_CODE_MIN_HITS:
            findings.append(_mk("CL-09", rel, index + 1, "<comment>",
                                f"comment@{index + 1}",
                                f"注释代码块：{len(block)} 行被注释的代码（疑似废弃实现）",
                                "确认已被替代后删除（git 历史即备份层）；保留解释性说明请改写为自然语言注释",
                                Severity.LOW, 0.25))
        index = end
    return findings


def _code_hits(block: list[str]) -> int:
    """块内「像代码」的注释行数量。"""
    return sum(1 for line in block if _CODE_HINT.match(line))


def _mk(rule_id: str, rel: str, line: int, symbol: str, key: str, message: str,
        fix_hint: str, severity: Severity, effort: float) -> Finding:
    """构造 Finding（CL 规则共用）。

    ``key`` 为指纹稳定段的语义标识：符号级规则用符号名（改行不产生新 finding），
    位置级规则（不可达/条件/注释块）用行号。
    """
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
