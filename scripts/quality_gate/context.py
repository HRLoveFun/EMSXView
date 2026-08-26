"""检测器共享上下文 — 文件收集 / AST 缓存 / 时间预算。

full 与 staged 两档模式的差异体现为「判定对象文件集」不同：
import 图 / 调用计数等全库索引总是基于 ``all_python_files`` 构建，
因此增量模式不会因图不完整而误报。
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config
from .ast_utils import read_text_safe, parse_module


def collect_python_files(root: Path, scan_roots: list[str]) -> list[Path]:
    """收集指定扫描根下的全部 Python 文件（按排除目录过滤）。"""
    files: list[Path] = []
    for rel_root in scan_roots:
        base = root / rel_root
        if not base.exists():
            continue
        files.extend(_iter_py(base))
    return sorted(set(files))


def collect_all_python_files(root: Path) -> list[Path]:
    """全库收集 Python 文件（import 图 / 调用计数的索引范围）。"""
    return _iter_py(root)


def collect_frontend_files(root: Path) -> list[Path]:
    """收集前端源码文件（.ts/.tsx）。"""
    base = root / config.FRONTEND_SCAN_ROOT
    if not base.exists():
        return []
    return sorted(
        p for p in base.rglob("*")
        if p.suffix in (".ts", ".tsx")
        and not any(part in config.GLOBAL_EXCLUDE_DIRS for part in p.parts)
    )


def _iter_py(base: Path) -> list[Path]:
    """递归收集 .py 文件，排除缓存/依赖目录。"""
    return sorted(
        p for p in base.rglob("*.py")
        if not any(part in config.GLOBAL_EXCLUDE_DIRS for part in p.parts)
    )


@dataclass
class ScanContext:
    """检测器共享上下文。"""

    root: Path                              # 项目根
    mode: str                               # "full" | "staged"
    python_files: list[Path]                # 判定对象（py）
    frontend_files: list[Path]              # 判定对象（ts/tsx）
    all_python_files: list[Path] = field(default_factory=list)   # 全库索引范围
    all_frontend_files: list[Path] = field(default_factory=list)
    deadline: float | None = None           # monotonic 截止时刻；None=无预算

    _trees: dict[Path, ast.Module | None] = field(default_factory=dict)
    _texts: dict[Path, str | None] = field(default_factory=dict)

    def tree(self, path: Path) -> ast.Module | None:
        """带缓存的 AST 解析（全库共享，检测器不得修改缓存树）。"""
        if path not in self._trees:
            self._trees[path] = parse_module(path)
        return self._trees[path]

    def text(self, path: Path) -> str | None:
        """带缓存的文本读取。"""
        if path not in self._texts:
            self._texts[path] = read_text_safe(path)
        return self._texts[path]

    def in_budget(self) -> bool:
        """是否仍在时间预算内（staged 模式 fail-open 保护）。"""
        return self.deadline is None or time.monotonic() < self.deadline
