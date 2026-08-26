"""OE-02 过度抽象检测器 — 单实现抽象基类 / 单调用方 1:1 传递函数。

两类信号：
1. **单实现抽象基类**：ABC 仅有一个子类，且唯一实现行数 < 阈值 —
   抽象层成本大于收益，可直接内联。零实现的 ABC 报 low（信息性）。
   Protocol 结构化类型豁免（鸭子类型实现不显式继承，零子类是常态）。
2. **单调用方 1:1 传递函数**：函数体只是把参数原样转发给另一个函数，
   且全库仅一个调用点 — 纯转发包装无增值逻辑。

类名/调用匹配基于简单名称（忽略 import 细节），容忍少量漏报，
换取零第三方依赖与低误报。
"""

from __future__ import annotations

import ast

from .. import config
from ..ast_utils import (
    base_names,
    class_line_count,
    decorator_names,
    iter_classes,
    iter_functions,
    make_fingerprint,
    rel_posix,
)
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

_EXEMPT_PARTS = config.OE_EXEMPT_DIR_PARTS

# 抽象基类识别：基类名含这些关键词，或方法带 @abstractmethod
_ABSTRACT_BASE_NAMES = {"ABC", "ABCMeta"}
_ABSTRACT_DECORATOR = "abstractmethod"


def detect(ctx: ScanContext) -> list[Finding]:
    """全库索引类图与调用计数后，对判定对象文件输出 Finding。"""
    classes = _index_classes(ctx)
    call_counts = _index_call_counts(ctx)
    findings: list[Finding] = []
    findings.extend(_detect_single_impl_abstraction(ctx, classes))
    findings.extend(_detect_forwarding_wrappers(ctx, call_counts))
    return findings


# ── 类索引 ────────────────────────────────────────────────────────

def _index_classes(ctx: ScanContext) -> dict[str, list[ast.ClassDef]]:
    """全库类名 → ClassDef 列表（同名类按出现顺序收集）。"""
    classes: dict[str, list[ast.ClassDef]] = {}
    for path in ctx.all_python_files:
        tree = ctx.tree(path)
        if tree is None:
            continue
        for cls in iter_classes(tree):
            classes.setdefault(cls.name, []).append(cls)
    return classes


def _is_abstract_class(cls: ast.ClassDef) -> bool:
    """是否为抽象基类（ABC 风格；Protocol 结构化类型不算）。"""
    if any(b in _ABSTRACT_BASE_NAMES for b in base_names(cls)):
        return True
    return any(
        _ABSTRACT_DECORATOR in decorator_names(func)
        for func in cls.body
        if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef))
    )


def _is_exception_class(cls: ast.ClassDef, classes: dict[str, list[ast.ClassDef]]) -> bool:
    """是否为异常层级（继承链上溯到 Exception — 深层级是框架常态）。"""
    seen: set[str] = set()
    queue = base_names(cls)
    while queue:
        name = queue.pop()
        if name in seen:
            continue
        seen.add(name)
        if name == "Exception":
            return True
        for parent in classes.get(name, []):
            queue.extend(base_names(parent))
    return False


# ── 信号 1：单实现抽象基类 ─────────────────────────────────────────

def _detect_single_impl_abstraction(ctx: ScanContext,
                                    classes: dict[str, list[ast.ClassDef]]) -> list[Finding]:
    """输出单实现/零实现抽象基类 Finding。"""
    # 全库继承边：基类名 → 直接子类 ClassDef 列表
    subclasses: dict[str, list[ast.ClassDef]] = {}
    for defs in classes.values():
        for cls in defs:
            for base in base_names(cls):
                if base != cls.name:
                    subclasses.setdefault(base, []).append(cls)

    findings: list[Finding] = []
    for path in ctx.python_files:
        rel = rel_posix(path, ctx.root)
        if any(part in _EXEMPT_PARTS for part in path.parts):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        for cls in iter_classes(tree):
            if not _is_abstract_class(cls):
                continue
            if _is_exception_class(cls, classes):
                continue
            children = subclasses.get(cls.name, [])
            findings.extend(_judge_abstraction(rel, cls, children))
    return findings


def _judge_abstraction(rel: str, cls: ast.ClassDef,
                       children: list[ast.ClassDef]) -> list[Finding]:
    """按子类数量判定抽象层是否过度。"""
    if len(children) == 1:
        impl_loc = class_line_count(children[0])
        if impl_loc < config.MAX_SINGLE_IMPL_LOC:
            return [_finding(
                rel, cls, Severity.MEDIUM,
                f"抽象基类仅有一个实现 {children[0].name}（{impl_loc} 行 < "
                f"{config.MAX_SINGLE_IMPL_LOC} 行），抽象层成本大于收益",
                f"移除 {cls.name} 抽象层，直接使用 {children[0].name}；"
                "若预期未来出现多实现，先 suppressed 并注明理由",
                0.5)]
        return []
    if len(children) == 0:
        return [_finding(
            rel, cls, Severity.LOW,
            "抽象基类无任何实现（可能为预留或死代码）",
            "确认是否有使用计划；无计划则删除；有计划则 suppressed 并注明",
            0.25)]
    return []


# ── 信号 2：单调用方 1:1 传递函数 ──────────────────────────────────

def _index_call_counts(ctx: ScanContext) -> dict[str, int]:
    """全库函数调用计数：按调用目标的简单名称聚合。"""
    counts: dict[str, int] = {}
    for path in ctx.all_python_files:
        tree = ctx.tree(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                counts[node.func.id] = counts.get(node.func.id, 0) + 1
            elif isinstance(node.func, ast.Attribute):
                counts[node.func.attr] = counts.get(node.func.attr, 0) + 1
    return counts


def _detect_forwarding_wrappers(ctx: ScanContext,
                                call_counts: dict[str, int]) -> list[Finding]:
    """输出单调用方 1:1 传递函数 Finding。"""
    findings: list[Finding] = []
    for path in ctx.python_files:
        rel = rel_posix(path, ctx.root)
        if any(part in _EXEMPT_PARTS for part in path.parts):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        for func in iter_functions(tree):
            if _is_forwarding_wrapper(func) and call_counts.get(func.name, 0) == 1:
                findings.append(_finding(
                    rel, func, Severity.MEDIUM,
                    "1:1 传递函数：参数原样转发且全库仅一个调用点，纯包装无增值",
                    "内联到唯一调用方；若为 API 边界预留请 suppressed 并注明",
                    0.5))
    return findings


def _is_forwarding_wrapper(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """判定是否为 1:1 传递函数（豁免装饰器挂点 / super 覆写 / dunder）。"""
    if func.decorator_list:
        return False                      # 框架挂点（router/property 等）
    if func.name.startswith("__"):
        return False                      # 魔术方法
    # 实质语句 = 非 docstring 的 body 语句；1:1 传递 = 恰好一条 return Call(...)
    stmts = _substance_stmts(func.body)
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Return):
        return False
    # 函数体不得含 super()（继承协议覆写）
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Call) \
                and isinstance(node.func.value.func, ast.Name) \
                and node.func.value.func.id == "super":
            return False
    call = stmts[0].value
    return isinstance(call, ast.Call) and _args_all_forwarded(call, func)


def _args_all_forwarded(call: ast.Call, func: ast.FunctionDef
                        | ast.AsyncFunctionDef) -> bool:
    """调用参数是否全部为函数形参名的原样转发。"""
    params = {a.arg for a in func.args.posonlyargs + func.args.args + func.args.kwonlyargs}
    if func.args.vararg:
        params.add(func.args.vararg.arg)
    if func.args.kwarg:
        params.add(func.args.kwarg.arg)
    for arg in call.args:
        if not (isinstance(arg, ast.Name) and arg.id in params):
            return False
    for kw in call.keywords:
        if kw.arg is None or not (isinstance(kw.value, ast.Name) and kw.value.id in params):
            return False
    return True


def _substance_stmts(body: list[ast.stmt]) -> list[ast.stmt]:
    """过滤 docstring 后的实质语句。"""
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) \
            and isinstance(body[0].value.value, str):
        return body[1:]
    return body


def _finding(rel: str, node: ast.ClassDef | ast.FunctionDef, severity: Severity,
             message: str, fix_hint: str, effort: float) -> Finding:
    """构造 OE-02 Finding。"""
    return Finding(
        rule_id="OE-02",
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=node.lineno,
        symbol=node.name,
        message=message,
        fix_hint=fix_hint,
        fingerprint=make_fingerprint("OE-02", rel, node.name),
        est_effort_h=effort,
    )
