"""装饰器名提取 — CL-02 / CL-05 共用的框架豁免判定输入。

标准库 ``ast`` 无法直接回答「这个函数是否被框架调用」，但装饰器是最可靠的线索：
``@router.get("/x")`` 中的 ``router`` / ``get`` 足以判定为路由处理器，
从而避免把「零引用」误判为死代码（本项目最主要的误报来源）。
"""

from __future__ import annotations

import ast

from . import config


def decorator_tokens(node: ast.AST) -> set[str]:
    """节点装饰器涉及的全部名字（含属性链上的接收者名）。

    例：``@router.get("/x")`` → ``{"router", "get"}``；``@lru_cache(maxsize=8)`` → ``{"lru_cache"}``。
    """
    tokens: set[str] = set()
    for decorator in getattr(node, "decorator_list", []):
        tokens |= _tokens_of(decorator)
    return tokens


def _tokens_of(expr: ast.AST) -> set[str]:
    """单个装饰器表达式的名字集合。"""
    if isinstance(expr, ast.Call):
        return _tokens_of(expr.func)
    if isinstance(expr, ast.Attribute):
        return _attribute_chain(expr)
    name = getattr(expr, "id", None)
    return {name} if isinstance(name, str) else set()


def _attribute_chain(expr: ast.Attribute) -> set[str]:
    """属性链上的全部名字（``a.b.c`` → {"a","b","c"}）。"""
    tokens: set[str] = set()
    node: ast.AST = expr
    while isinstance(node, ast.Attribute):
        tokens.add(node.attr)
        node = node.value
    root = getattr(node, "id", None)
    if isinstance(root, str):
        tokens.add(root)
    return tokens


def is_framework_decorated(tokens: set[str]) -> bool:
    """装饰器是否表明符号由框架/运行时调用（豁免零引用判定）。"""
    known = (config.DEAD_SYMBOL_EXEMPT_DECORATORS
             | config.ROUTE_DECORATOR_METHODS
             | config.ROUTE_DECORATOR_TOKENS)
    return bool(tokens & known)
