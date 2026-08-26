"""OE-04 重复代码块检测器 — AST 归一化 + 整函数体匹配。

算法：函数体 AST 归一化（抹标识符/字面量差异，保留结构与属性名）后
unparse 为源码，跨函数比对完全相同的归一化体（≥ 阈值行数）。
典型覆盖「复制函数后改名改量名」场景；同文件内重复同样检出。

v1 仅做整函数级匹配（低误报）；函数内局部块匹配留待 v2。
"""

from __future__ import annotations

import ast
import copy
import hashlib

from .. import config
from ..ast_utils import iter_functions, make_fingerprint, normalize_body, rel_posix
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

_EXEMPT_PARTS = config.OE_EXEMPT_DIR_PARTS


def detect(ctx: ScanContext) -> list[Finding]:
    """收集归一化函数体指纹，输出重复组内每实例的 Finding。"""
    # 归一化体哈希 → 出现位置列表
    groups: dict[str, list[tuple[str, int, str, int]]] = {}
    for path in ctx.python_files:
        rel = rel_posix(path, ctx.root)
        if _is_exempt(path):
            continue
        tree = ctx.tree(path)
        if tree is None:
            continue
        for func in iter_functions(tree):
            entry = _normalize_function(func)
            if entry is None:
                continue
            body_hash, line_count = entry
            groups.setdefault(body_hash, []).append((rel, func.lineno, func.name, line_count))

    findings: list[Finding] = []
    for body_hash, occurrences in groups.items():
        if len(occurrences) < 2:
            continue
        findings.extend(_group_findings(body_hash, occurrences))
    return findings


def _normalize_function(func: ast.FunctionDef | ast.AsyncFunctionDef
                        ) -> tuple[str, int] | None:
    """函数体归一化并哈希；行数不足阈值返回 None。

    深拷贝后归一化 — 不得修改 ctx 缓存的共享 AST。
    """
    normalized = normalize_body(copy.deepcopy(func.body))
    lines = normalized.splitlines()
    if len(lines) < config.MIN_DUPLICATION_LINES:
        return None
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest(), len(lines)


def _group_findings(body_hash: str,
                    occurrences: list[tuple[str, int, str, int]]) -> list[Finding]:
    """重复组 → 每实例一个 Finding（含其他实例位置提示）。"""
    line_count = occurrences[0][3]
    # 同一函数签名重复出现（如重载/同名嵌套）只取一次
    deduped = _dedup_occurrences(occurrences)
    if len(deduped) < 2:
        return []
    others_hint = "；".join(
        f"{rel}:{line}" for rel, line, _, _ in deduped
    )
    effort = max(0.5, line_count / 40.0)
    return [
        Finding(
            rule_id="OE-04",
            ruleset=RuleSet.OE,
            severity=Severity.HIGH,
            file=rel,
            line=line,
            symbol=name,
            message=(
                f"重复代码块：归一化后 {line_count} 行与 {len(deduped) - 1} 处完全一致"
                f"（{others_hint}）"
            ),
            fix_hint="提取公共函数/基类，参数化差异点；确属业务隔离的副本请 suppressed 注明",
            fingerprint=make_fingerprint("OE-04", rel, name, body_hash[:16]),
            est_effort_h=round(effort, 2),
        )
        for rel, line, name, _ in deduped
    ]


def _dedup_occurrences(occurrences: list[tuple[str, int, str, int]]
                       ) -> list[tuple[str, int, str, int]]:
    """按 (文件, 函数名) 去重（同名函数重载场景只计一次）。"""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, int, str, int]] = []
    for entry in occurrences:
        key = (entry[0], entry[2])
        if key in seen:
            continue
        seen.add(key)
        out.append(entry)
    return out


def _is_exempt(path) -> bool:
    """重复检测豁免：测试 / 运维回填 / schema 常量区。"""
    parts = path.parts
    if any(part in _EXEMPT_PARTS for part in parts):
        return True
    rel = path.as_posix()
    return any(frag in rel for frag in config.DUPLICATION_EXEMPT_PARTS)
