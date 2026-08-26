"""OE-05 复杂度超标检测器 — 圈复杂度 / 嵌套深度 / 参数个数 / 函数长度。

四项独立阈值判定，各自生成 Finding；fingerprint 绑定「文件+符号+维度」
（非内容哈希），复杂度问题随符号存在而非随代码片段存在。
"""

from __future__ import annotations

import ast

from .. import config
from ..ast_utils import (
    cyclomatic_complexity,
    func_line_count,
    iter_functions,
    make_fingerprint,
    nesting_depth,
    param_count,
    rel_posix,
)
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

# 判定豁免：测试代码复杂度是常态（参数化用例天然分支多）
_EXEMPT_PARTS = config.OE_EXEMPT_DIR_PARTS


def detect(ctx: ScanContext) -> list[Finding]:
    """扫描判定对象文件的全部函数，输出超标 Finding。"""
    findings: list[Finding] = []
    for path in ctx.python_files:
        rel = rel_posix(path, ctx.root)
        if any(part in _EXEMPT_PARTS for part in path.parts):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        findings.extend(_scan_file(tree, rel))
    return findings


def _scan_file(tree: ast.Module, rel: str) -> list[Finding]:
    """单文件内全部函数的阈值检查。"""
    findings: list[Finding] = []
    for func in iter_functions(tree):
        cc = cyclomatic_complexity(func)
        depth = nesting_depth(func.body)
        params = param_count(func)
        lines = func_line_count(func)

        if cc > config.MAX_CYCLOMATIC:
            findings.append(_finding(rel, func, "cyclomatic",
                f"圈复杂度 {cc} 超过阈值 {config.MAX_CYCLOMATIC}",
                f"拆分为小函数或用查表替代分支链（当前 CC={cc}）",
                Severity.HIGH if cc > config.MAX_CYCLOMATIC_HIGH else Severity.MEDIUM,
                max(0.5, (cc - config.MAX_CYCLOMATIC) / 5.0)))
        if depth > config.MAX_NESTING:
            findings.append(_finding(rel, func, "nesting",
                f"嵌套深度 {depth} 超过阈值 {config.MAX_NESTING}",
                "用 early return / 卫语句拍平嵌套，或将内层块提取为独立函数",
                Severity.MEDIUM, 1.0))
        if params > config.MAX_PARAMS:
            findings.append(_finding(rel, func, "params",
                f"参数个数 {params} 超过阈值 {config.MAX_PARAMS}",
                "收拢为单个配置对象（dataclass/pydantic），或拆分函数职责",
                Severity.LOW, 0.5))
        if lines > config.MAX_FUNC_LINES:
            findings.append(_finding(rel, func, "length",
                f"函数长度 {lines} 行超过阈值 {config.MAX_FUNC_LINES} 行",
                "按职责拆分为多个小函数（单一职责，每函数 ≤30 行最佳）",
                Severity.MEDIUM, max(0.5, (lines - config.MAX_FUNC_LINES) / 60.0)))
    return findings


def _finding(rel: str, func: ast.FunctionDef | ast.AsyncFunctionDef, kind: str,
             message: str, fix_hint: str, severity: Severity, effort: float) -> Finding:
    """构造 OE-05 Finding。"""
    return Finding(
        rule_id="OE-05",
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=func.lineno,
        symbol=func.name,
        message=message,
        fix_hint=fix_hint,
        fingerprint=make_fingerprint("OE-05", rel, func.name, kind),
        est_effort_h=round(effort, 2),
    )
