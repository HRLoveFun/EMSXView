"""OE-01 冗余模块检测器 — 全库 import 图 + 入口可达性分析。

算法：
1. 全库收集 py 文件，构建 import 有向图（静态 import 多视角解析
   + ``importlib.import_module("X")`` / ``__import__("X")`` 字符串兜底）
2. 入口 = 文件名/目录白名单命中（CLI / pytest / 部署器触达的文件）
3. BFS 可达性：入口不可达的业务模块 → 冗余候选

多视角解析（各 sys.path 根 + 相对导入）宁可多连边，减少死模块误报；
``__init__.py`` 全部豁免（包可见性语义复杂，单独判定误报率高）。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from .. import config
from ..ast_utils import make_fingerprint, rel_posix
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

# 动态导入兜底：importlib.import_module("X") / __import__("X") 字符串字面量
_DYNAMIC_IMPORT = re.compile(
    r"(?:import_module|__import__)\(\s*['\"]([\w.]+)['\"]"
)
# f-string 动态导入：import_module(f"pkg.{name}") — 静态前缀 pkg 整包视为可达（保守）
_DYNAMIC_IMPORT_FSTRING = re.compile(
    r"(?:import_module|__import__)\(\s*f['\"]([\w.]+)\."
)

# import 名解析的视角根（各包的 sys.path 挂载点；多视角宁可多命中）
_RESOLVE_ROOTS: tuple[str, ...] = (
    "",                      # 仓库根：DataPipeline.x / CostView.src.x / platform_data.x
    "backend/api",           # from routers import ... / from services import ...
    "backend",
    "DataPipeline",
    "CostView/src",
    "CostView/api",
    "CostView",
    "platform_data",
    "MarketView",
)


def detect(ctx: ScanContext) -> list[Finding]:
    """构建 import 图并输出不可达业务模块的 Finding。"""
    file_set = set(ctx.all_python_files)
    if not file_set:
        return []

    edges = _build_import_graph(ctx, file_set)
    reachable = _reachable_from(_entry_files(ctx), edges)

    findings: list[Finding] = []
    for path in ctx.python_files:
        if path in reachable:
            continue
        rel = rel_posix(path, ctx.root)
        if _is_exempt(path, rel):
            continue
        findings.append(Finding(
            rule_id="OE-01",
            ruleset=RuleSet.OE,
            severity=Severity.MEDIUM,
            file=rel,
            line=1,
            symbol=path.stem,
            message="冗余模块：import 图中无任何入口可达（无消费者引用）",
            fix_hint="确认后删除，或移入 scripts/ops 运维区；若为动态加载场景"
                     "请加入 config.DEAD_MODULE_EXEMPT 豁免并注明",
            fingerprint=make_fingerprint("OE-01", rel),
            est_effort_h=0.5,
        ))
    return findings


# ── import 图构建 ─────────────────────────────────────────────────

def _build_import_graph(ctx: ScanContext, file_set: set[Path]) -> dict[Path, set[Path]]:
    """文件 → 其 import 解析到的文件集合（含子模块与动态导入兜底）。"""
    edges: dict[Path, set[Path]] = {}
    for path in ctx.all_python_files:
        targets: set[Path] = set()
        tree = ctx.tree(path)
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        targets |= _resolve_import(alias.name, 0, path, ctx.root, file_set)
                elif isinstance(node, ast.ImportFrom):
                    level = node.level or 0
                    targets |= _resolve_import(node.module, level, path, ctx.root, file_set)
                    # from X import name / from . import name：name 可能是子模块
                    for alias in node.names:
                        if level > 0:
                            targets |= _resolve_relative(alias.name, level, path, file_set)
                        elif node.module:
                            targets |= _resolve_import(
                                f"{node.module}.{alias.name}", 0, path, ctx.root, file_set)
        text = ctx.text(path)
        if text is not None:
            for module in _DYNAMIC_IMPORT.findall(text):
                targets |= _resolve_import(module, 0, path, ctx.root, file_set)
            # f-string 前缀（如 import_module(f"routers.{name}")）：前缀包整目录可达
            for prefix in _DYNAMIC_IMPORT_FSTRING.findall(text):
                targets |= _package_files(ctx, prefix, file_set)
        edges[path] = targets
    return edges


def _package_files(ctx: ScanContext, prefix: str, file_set: set[Path]) -> set[Path]:
    """f-string 动态导入的前缀包 → 包目录下全部 py 文件（保守可达）。"""
    matched: set[Path] = set()
    for view in _RESOLVE_ROOTS:
        base = ctx.root / view / _module_path(prefix)
        if (base / "__init__.py") in file_set or base.with_suffix(".py") in file_set:
            matched |= {p for p in file_set if base == p.parent or base in p.parents}
            break
    return matched


def _resolve_import(module: str | None, level: int, importer: Path,
                    root: Path, file_set: set[Path]) -> set[Path]:
    """将一条 import 解析为候选文件集合（多视角 + 相对导入）。"""
    if level > 0:
        if not module:
            return set()
        base = _relative_base(importer, level)
        if base is None:
            return set()
        return _match_files([base / _module_path(module)], file_set)

    if not module:
        return set()
    candidates = [root / view / _module_path(module) for view in _RESOLVE_ROOTS]
    return _match_files(candidates, file_set)


def _resolve_relative(submodule: str, level: int, importer: Path,
                      file_set: set[Path]) -> set[Path]:
    """相对导入的子模块解析（``from . import x`` → 同目录 x.py）。"""
    base = _relative_base(importer, level)
    if base is None:
        return set()
    return _match_files([base / _module_path(submodule)], file_set)


def _relative_base(importer: Path, level: int) -> Path | None:
    """相对导入基准目录：importer 向上 level 层；越界返回 None。"""
    base = importer.parent
    for _ in range(level - 1):
        base = base.parent
        if len(base.parts) <= 1:
            return None
    return base


def _module_path(module: str) -> str:
    """点分模块名 → 相对路径（'a.b' → 'a/b'）。"""
    return "/".join(module.split("."))


def _match_files(candidates: list[Path], file_set: set[Path]) -> set[Path]:
    """候选路径补全扩展名后与文件集合求交。"""
    matched: set[Path] = set()
    for cand in candidates:
        for probe in (cand.with_suffix(".py"), cand / "__init__.py"):
            if probe in file_set:
                matched.add(probe)
    return matched


# ── 入口与可达性 ──────────────────────────────────────────────────

def _entry_files(ctx: ScanContext) -> list[Path]:
    """入口文件：白名单命中的全库文件。"""
    return [p for p in ctx.all_python_files if _is_entry(p, ctx.root)]


def _is_entry(path: Path, root: Path) -> bool:
    """是否为图入口（文件名或目录命中白名单）。"""
    if path.name in config.ENTRY_FILE_NAMES:
        return True
    return any(part in config.ENTRY_DIR_PARTS for part in path.parts)


def _reachable_from(entries: list[Path], edges: dict[Path, set[Path]]) -> set[Path]:
    """从入口 BFS 计算可达文件集合。"""
    seen: set[Path] = set(entries)
    queue: list[Path] = list(entries)
    while queue:
        current = queue.pop()
        for target in edges.get(current, ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


def _is_exempt(path: Path, rel: str) -> bool:
    """死模块判定豁免：__init__ / 测试 / 入口文件 / 人工豁免清单。"""
    if path.name == "__init__.py":
        return True
    if any(part in config.ENTRY_DIR_PARTS for part in path.parts):
        return True
    if any(part in config.OE_EXEMPT_DIR_PARTS for part in path.parts):
        return True
    return rel in config.DEAD_MODULE_EXEMPT
