"""文件级清理检测器 — CL-01 冗余文件 / CL-07 临时遗留 / CL-08 空壳模块。

CL-01 直接复用 OE-01 的 import 图可达性算法（不重写），仅扩大扫描范围并重标规则号，
使清理报告自带完整编号体系；避免与 quality_gate 形成两套图算法。
"""

from __future__ import annotations

import ast
from pathlib import Path

from scripts.quality_gate.ast_utils import make_fingerprint, rel_posix
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.detectors import dead_modules
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config


def detect(ctx: ScanContext) -> list[Finding]:
    """CL-01 + CL-07 + CL-08。"""
    return [*_dead_files(ctx), *_temp_leftovers(ctx), *_empty_modules(ctx)]


# ── CL-01 冗余文件（包装 OE-01）────────────────────────────────────

def _dead_files(ctx: ScanContext) -> list[Finding]:
    """import 图中无入口可达的自有文件（零引用）。"""
    findings: list[Finding] = []
    for src in dead_modules.detect(ctx):
        if src.file in config.DEAD_FILE_EXEMPT or _is_cli_entry(Path(src.file)):
            continue
        findings.append(Finding(
            rule_id="CL-01",
            ruleset=RuleSet.OE,
            severity=Severity.HIGH,
            file=src.file,
            line=1,
            symbol=src.symbol,
            message="冗余文件：import 图中无任何入口可达（零引用）",
            fix_hint="确认无动态加载/子进程调用后删除（git 历史可恢复）；"
                     "休眠运维接口应加注释说明归属，或列入 config.DEAD_FILE_EXEMPT",
            fingerprint=make_fingerprint("CL-01", src.file),
            est_effort_h=0.5,
        ))
    return findings


# ── CL-07 临时/调试遗留文件 ───────────────────────────────────────

def _temp_leftovers(ctx: ScanContext) -> list[Finding]:
    """命名即临时的文件（与 cleanup-tmp 命令互补：这里覆盖非根目录的业务树内残留）。"""
    findings: list[Finding] = []
    for path in [*ctx.python_files, *ctx.frontend_files]:
        if _is_exempt_dir(path):
            continue
        reason = _temp_reason(path.stem)
        if reason is None:
            continue
        rel = rel_posix(path, ctx.root)
        findings.append(Finding(
            rule_id="CL-07",
            ruleset=RuleSet.OE,
            severity=Severity.HIGH,
            file=rel,
            line=1,
            symbol=path.stem,
            message=f"临时/调试遗留文件：{reason}",
            fix_hint="按 .codebuddy/rules/coding-style.md「临时代码文件」规范：临时件归 _tmp/ 并任务结束即清理；"
                     "需长期保留则迁 scripts/ops/ 或 docs/ 并改去临时命名",
            fingerprint=make_fingerprint("CL-07", rel),
            est_effort_h=0.25,
        ))
    return findings


def _temp_reason(stem: str) -> str | None:
    """文件名命中临时命名特征时返回原因，否则 None。"""
    for pattern, reason in config.TEMP_FILE_PATTERNS:
        if pattern.search(stem):
            return reason
    return None


# ── CL-08 空壳模块 ────────────────────────────────────────────────

def _empty_modules(ctx: ScanContext) -> list[Finding]:
    """除 docstring/pass/__future__ 外无任何顶层语句的模块（删除无副作用）。"""
    findings: list[Finding] = []
    for path in ctx.python_files:
        if path.name == "__init__.py" or _is_exempt_dir(path):
            continue
        tree = ctx.tree(path)
        if tree is None or not _is_empty_module(tree):
            continue
        rel = rel_posix(path, ctx.root)
        findings.append(Finding(
            rule_id="CL-08",
            ruleset=RuleSet.OE,
            severity=Severity.LOW,
            file=rel,
            line=1,
            symbol=path.stem,
            message="空壳模块：除 docstring/pass 外无任何顶层语句（无副作用）",
            fix_hint="确认无副作用导入（如框架自动发现）后删除；仅作为包占位则保留 __init__.py 即可",
            fingerprint=make_fingerprint("CL-08", rel),
            est_effort_h=0.25,
        ))
    return findings


def _is_empty_module(tree: ast.Module) -> bool:
    """顶层语句是否全部为无副作用占位（docstring / pass / __future__）。"""
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue                                   # docstring / 裸字面量
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        return False
    return True


def _is_exempt_dir(path: Path) -> bool:
    """测试与依赖目录豁免。"""
    return any(part in config.EXEMPT_DIR_PARTS for part in path.parts)


def _is_cli_entry(path: Path) -> bool:
    """CLI 入口文件豁免（人工调用即入口，import 图中天然无入边）。"""
    return path.stem in config.CLI_ENTRY_NAMES or \
        path.stem.endswith(config.CLI_ENTRY_SUFFIXES)
