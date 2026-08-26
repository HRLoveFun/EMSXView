"""AST 公共工具 — 根定位 / 文件收集 / 模块解析 / 复杂度计算 / 归一化指纹。

被所有 OE 检测器共享；零第三方依赖（纯标准库 ast/hashlib）。
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Iterator

# 项目根定位 marker（AP-16：单一信息源，禁止硬编码"向上 N 层"）
ROOT_MARKER = ".emsxview-root"


def find_project_root(start: Path) -> Path:
    """向上查找 ``.emsxview-root`` marker 定位项目根。"""
    for dir_path in (start, *start.parents):
        if (dir_path / ROOT_MARKER).exists():
            return dir_path
    raise FileNotFoundError(f"未找到 {ROOT_MARKER} marker，无法定位项目根")


def read_text_safe(path: Path) -> str | None:
    """读取文件文本，IO/编码失败返回 None（容错，不中断扫描）。"""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def parse_module(path: Path) -> ast.Module | None:
    """解析 Python 文件为 AST，语法错误 / IO 失败返回 None。"""
    text = read_text_safe(path)
    if text is None:
        return None
    try:
        return ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError):
        return None


def rel_posix(path: Path, root: Path) -> str:
    """仓库相对 posix 风格路径（Windows 兼容）。"""
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def iter_functions(tree: ast.Module) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    """遍历 AST 中全部函数定义（含嵌套函数与类方法）。"""
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def iter_classes(tree: ast.Module) -> Iterator[ast.ClassDef]:
    """遍历 AST 中全部类定义。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            yield node


def iter_imports(tree: ast.Module) -> Iterator[tuple[str | None, int]]:
    """提取 (模块名, level) — 涵盖 ``import X.Y`` 与 ``from .x import y``。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, 0
        elif isinstance(node, ast.ImportFrom):
            yield node.module, node.level or 0


def base_names(cls: ast.ClassDef) -> list[str]:
    """类基类的简单名称列表（Name.id / Attribute.attr）。"""
    names: list[str] = []
    for base in cls.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def decorator_names(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """函数装饰器的简单名称列表（``@x.y`` 取末段）。"""
    names: list[str] = []
    for dec in func.decorator_list:
        if isinstance(dec, ast.Name):
            names.append(dec.id)
        elif isinstance(dec, ast.Attribute):
            names.append(dec.attr)
        elif isinstance(dec, ast.Call):
            target = dec.func
            if isinstance(target, ast.Name):
                names.append(target.id)
            elif isinstance(target, ast.Attribute):
                names.append(target.attr)
    return names


# ── 复杂度度量（OE-05）─────────────────────────────────────────────

_BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.IfExp)


def cyclomatic_complexity(func: ast.AST) -> int:
    """圈复杂度：基础 1 + 分支节点计数（if/for/while/except/三元/and/or/comprehension/match）。"""
    cc = 1
    for node in ast.walk(func):
        if isinstance(node, _BRANCH_NODES):
            cc += 1
        elif isinstance(node, ast.BoolOp):
            cc += len(node.values) - 1
        elif isinstance(node, ast.Assert):
            cc += 1
        elif isinstance(node, ast.comprehension):
            cc += 1 + len(node.ifs)
        elif isinstance(node, ast.match_case):
            cc += 1
    return cc


_NESTABLE = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith)


def nesting_depth(body: list[ast.stmt]) -> int:
    """语句体嵌套深度：顶层=0，进入 if/for/while/try/with 体 +1（elif 天然 +1）。"""
    best = 0
    stack: list[tuple[list[ast.stmt], int]] = [(body, 0)]
    while stack:
        stmts, depth = stack.pop()
        best = max(best, depth)
        for stmt in stmts:
            for child_body in _stmt_bodies(stmt):
                stack.append((child_body, depth + 1))
    return best


def _stmt_bodies(stmt: ast.stmt) -> list[list[ast.stmt]]:
    """复合语句的直接子语句体列表。"""
    if isinstance(stmt, (ast.If, ast.For, ast.AsyncFor, ast.While)):
        return [stmt.body, *([stmt.orelse] if stmt.orelse else [])]
    if isinstance(stmt, ast.Try):
        return [stmt.body, stmt.finalbody, *(h.body for h in stmt.handlers)]
    if isinstance(stmt, (ast.With, ast.AsyncWith)):
        return [stmt.body]
    return []


def param_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """参数个数（含 *args/**kwargs），方法首参 self/cls 不计。"""
    args = func.args
    count = len(args.posonlyargs) + len(args.args) + len(args.kwonlyargs)
    count += (1 if args.vararg else 0) + (1 if args.kwarg else 0)
    if args.args and args.args[0].arg in ("self", "cls"):
        count -= 1
    return count


def func_line_count(func: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """函数物理行数（def 行至最后一行，不含装饰器）。"""
    return (func.end_lineno or func.lineno) - func.lineno + 1


def class_line_count(cls: ast.ClassDef) -> int:
    """类物理行数。"""
    return (cls.end_lineno or cls.lineno) - cls.lineno + 1


# ── 归一化与指纹（OE-04 / 基线追踪）────────────────────────────────


class _Normalizer(ast.NodeTransformer):
    """归一化 AST — 抹去标识符与字面量差异，保留结构与属性名。

    抹去：变量/参数名 → ``_v``、字符串 → ``S``、数字 → ``0``。
    保留：结构关键字、属性名（承载语义，抹去会大量误报）。
    """

    def visit_Name(self, node: ast.Name) -> ast.Name:
        node.id = "_v"
        return node

    def visit_arg(self, node: ast.arg) -> ast.arg:
        node.arg = "_v"
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if isinstance(node.value, str):
            node.value = "S"
        elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            node.value = 0
        return node


def normalize_body(body: list[ast.stmt]) -> str:
    """语句体归一化源码（入参会被修改，调用方需传入可变副本）。"""
    _Normalizer().visit(ast.Module(body=body, type_ignores=[]))
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


def make_fingerprint(*parts: str) -> str:
    """生成 finding 指纹（sha1，跨扫描追踪同一问题的生命周期）。"""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()
