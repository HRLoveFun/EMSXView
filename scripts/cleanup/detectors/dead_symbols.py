"""CL-02 过时符号 — 模块级零引用函数 / 类 / 常量。

判定方式：符号名在整个「代码语料」（全库 .py + .ts/.tsx，排除 docs/specs/plans）
中仅出现 1 次（即只有自身定义处）。

为何用「语料词元计数」而非 AST 引用图：
- 字符串形式的动态引用（``getattr("foo")``、注册表 ``{"foo": ...}``、DI 名字、子进程调用）
  都能被词元计数兜底，天然零误报；
- 代价是漏报（符号被注释或文档提及即不再报告）。清理场景的原则是
  「漏报可接受、误删不可接受」，故取此保守方向。
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

from scripts.quality_gate.ast_utils import make_fingerprint, rel_posix
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config
from ..names import decorator_tokens, is_framework_decorated

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def detect(ctx: ScanContext) -> list[Finding]:
    """扫描模块级符号，输出全库零引用候选项。"""
    counts = _token_counts(ctx)
    findings: list[Finding] = []
    for path in ctx.python_files:
        if path.name == "__init__.py" or _is_exempt(path):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        rel = rel_posix(path, ctx.root)
        for node in tree.body:
            finding = _judge(node, rel, counts)
            if finding is not None:
                findings.append(finding)
    return findings


def _token_counts(ctx: ScanContext) -> Counter[str]:
    """全库代码语料的词元计数（字符串字面量同样被计数——动态引用兜底）。"""
    counter: Counter[str] = Counter()
    corpus = [*ctx.all_python_files, *ctx.all_frontend_files]
    for path in corpus:
        if any(part in config.CORPUS_EXCLUDE_PARTS for part in path.parts):
            continue
        text = ctx.text(path)
        if text:
            counter.update(_TOKEN.findall(text))
    return counter


def _judge(node: ast.stmt, rel: str,
           counts: Counter[str]) -> Finding | None:
    """模块级语句的零引用判定（不命中返回 None）。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if _skip(node.name, decorator_tokens(node), counts):
            return None
        return _finding(rel, node, node.name, "函数", node.lineno)
    if isinstance(node, ast.ClassDef):
        if node.bases or _skip(node.name, decorator_tokens(node), counts):
            return None
        return _finding(rel, node, node.name, "类", node.lineno)
    name = _constant_name(node)
    if name is None or name in config.DEAD_SYMBOL_EXEMPT_NAMES:
        return None
    if len(name) < config.DEAD_SYMBOL_MIN_NAME_LEN or counts[name] > 1:
        return None
    return _finding(rel, node, name, "常量", node.lineno)


def _skip(name: str, decorators: set[str], counts: Counter[str]) -> bool:
    """通用豁免：dunder / 白名单 / 框架装饰器 / 语料中已被引用。"""
    if name.startswith("__") and name.endswith("__"):
        return True
    if name in config.DEAD_SYMBOL_EXEMPT_NAMES:
        return True
    if is_framework_decorated(decorators):
        return True
    return counts[name] > 1


def _constant_name(node: ast.stmt) -> str | None:
    """模块级 UPPER_SNAKE 常量名（Assign / AnnAssign 单目标）。"""
    target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
    if isinstance(node, ast.AnnAssign):
        target = node.target
    if not isinstance(target, ast.Name) or not target.id.isupper():
        return None
    return target.id


def _finding(rel: str, node: ast.stmt, name: str, kind: str, line: int) -> Finding:
    """构造 CL-02 Finding（长符号判 medium）。"""
    loc = (node.end_lineno or line) - line + 1
    severity = Severity.MEDIUM if loc >= config.DEAD_SYMBOL_MEDIUM_LOC else Severity.LOW
    return Finding(
        rule_id="CL-02",
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=line,
        symbol=name,
        message=f"过时{kind}：模块级 `{name}` 全库零引用（{loc} 行）",
        fix_hint="确认非装饰器/反射/外部入口调用后删除；确为预留 API 则 "
                 "`--suppress <fingerprint>` 豁免并注明理由",
        fingerprint=make_fingerprint("CL-02", rel, name),
        est_effort_h=0.5 if severity is Severity.MEDIUM else 0.25,
    )


def _is_exempt(path: Path) -> bool:
    """测试与依赖目录豁免。"""
    return any(part in config.EXEMPT_DIR_PARTS for part in path.parts)
