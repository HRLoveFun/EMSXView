"""OE-03 不必要设计模式检测器 — 过深继承链 / 单产品工厂。

保守策略（低误报优先）：
1. **过深继承链**：类继承链深度 > 阈值（Exception 层级豁免 — 框架常态）
2. **单产品工厂**：类名含 ``Factory`` 且其工厂方法只构造一种产品类

浅覆写子类等高误报信号第一版不做 — 监测机制的信誉靠低误报建立。
"""

from __future__ import annotations

import ast

from .. import config
from ..ast_utils import (
    base_names,
    iter_classes,
    make_fingerprint,
    rel_posix,
)
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

_EXEMPT_PARTS = config.OE_EXEMPT_DIR_PARTS


def detect(ctx: ScanContext) -> list[Finding]:
    """全库索引类图后，对判定对象文件输出 Finding。"""
    classes = _index_classes(ctx)
    findings: list[Finding] = []
    for path in ctx.python_files:
        rel = rel_posix(path, ctx.root)
        if any(part in _EXEMPT_PARTS for part in path.parts):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        for cls in iter_classes(tree):
            findings.extend(_check_class(rel, cls, classes))
    return findings


def _index_classes(ctx: ScanContext) -> dict[str, list[ast.ClassDef]]:
    """全库类名 → ClassDef 列表。"""
    classes: dict[str, list[ast.ClassDef]] = {}
    for path in ctx.all_python_files:
        tree = ctx.tree(path)
        if tree is None:
            continue
        for cls in iter_classes(tree):
            classes.setdefault(cls.name, []).append(cls)
    return classes


def _check_class(rel: str, cls: ast.ClassDef,
                 classes: dict[str, list[ast.ClassDef]]) -> list[Finding]:
    """单个类的两项设计模式检查。"""
    chain = _inheritance_chain(cls, classes)
    edges = len(chain) - 1
    if edges > config.MAX_INHERIT_DEPTH and not _ends_with_exception(chain, classes):
        return [_finding(
            rel, cls, Severity.MEDIUM,
            f"继承链过深（{edges} 层 > {config.MAX_INHERIT_DEPTH}）: "
            f"{' → '.join(chain)}",
            "改用组合（has-a）替代深层继承，或将中间层收敛为 mixin/工具函数",
            1.0)]
    if "Factory" in cls.name and _factory_has_single_product(cls):
        return [_finding(
            rel, cls, Severity.LOW,
            f"单产品工厂: {cls.name} 的方法只构造一种产品，工厂间接层无多态收益",
            "移除工厂类，让调用方直接构造产品；确有扩展预期则 suppressed 注明",
            1.0)]
    return []


def _inheritance_chain(cls: ast.ClassDef, classes: dict[str, list[ast.ClassDef]]) -> list[str]:
    """向上解析继承链（名称匹配，同名类取第一个定义）。"""
    chain = [cls.name]
    current = cls
    seen = {cls.name}
    while True:
        parents = [b for b in base_names(current) if b in classes and b not in seen]
        if not parents:
            break
        parent_name = parents[0]
        chain.append(parent_name)
        seen.add(parent_name)
        current = classes[parent_name][0]
    return chain


def _ends_with_exception(chain: list[str], classes: dict[str, list[ast.ClassDef]]) -> bool:
    """继承链是否上溯到 Exception（异常层级豁免）。"""
    return any(
        b == "Exception" or b.endswith("Error") or b.endswith("Exception")
        for name in chain
        for cls in classes.get(name, [])
        for b in base_names(cls)
    )


def _factory_has_single_product(cls: ast.ClassDef) -> bool:
    """工厂类的方法是否只构造一种产品类。"""
    products: set[str] = set()
    for node in ast.walk(cls):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        # 大写开头视为类构造（产品实例化）
        if node.func.id[0].isupper():
            products.add(node.func.id)
    return len(products) == 1


def _finding(rel: str, cls: ast.ClassDef, severity: Severity,
             message: str, fix_hint: str, effort: float) -> Finding:
    """构造 OE-03 Finding。"""
    return Finding(
        rule_id="OE-03",
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=cls.lineno,
        symbol=cls.name,
        message=message,
        fix_hint=fix_hint,
        fingerprint=make_fingerprint("OE-03", rel, cls.name),
        est_effort_h=effort,
    )
