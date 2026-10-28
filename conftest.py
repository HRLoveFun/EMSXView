"""仓库根 pytest 入口：全仓单命令按套件分进程执行。

背景：`backend/api` 与 `MarketView` 各自把服务目录放到 `sys.path` 首位，并
`import config` / `auth` / `routers` / `deps` 等同名顶层模块。单进程收集时，
先收集的套件会占住 `sys.modules`，后收集的套件随即 ImportError——实测根目录
`python -m pytest` 报 22 个收集错误（`MarketView/auth.py` 遮蔽 `backend/api/auth.py`），
反之把 backend 放前面则有 8 个 MarketView 收集错误（`routers` 被 backend 占住）。

两套件在**独立解释器**里各自成立，因此根目录的全仓调用改为逐套件子进程执行并
汇总退出码；显式传入路径时（含子进程自身的调用）行为不变，仍是普通单套件会话。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent

# 每项一个独立解释器：跨套件存在同名顶层模块，不能共享 sys.modules
SUITES = (
    "backend/api/tests",
    "CostView/tests",
    "MarketView/tests",
    "scripts/quality_gate/tests",
    "scripts/cleanup/tests",
)


def _write(text: str) -> None:
    """输出到 stdout；目标流不支持中文（重定向为 cp1252 等）时退化为 ASCII 转义。"""
    stream = sys.stdout
    try:
        stream.write(text)
    except UnicodeEncodeError:
        stream.write(text.encode("ascii", "backslashreplace").decode("ascii"))
    stream.flush()


def _is_full_repo_run(config) -> bool:
    """判定是否「仓库根、未指定路径」的全仓调用。"""
    try:
        if Path.cwd().resolve() != REPO_ROOT:
            return False
    except OSError:
        return False
    resolved = [Path(str(arg)).resolve() for arg in config.args]
    return resolved == [REPO_ROOT]


def pytest_cmdline_main(config):
    """全仓调用改为分套件子进程；返回聚合退出码，其它情况交回 pytest 默认流程。"""
    if not _is_full_repo_run(config):
        return None

    failures: list[tuple[str, int]] = []
    for suite in SUITES:
        if not (REPO_ROOT / suite).is_dir():
            continue
        _write(f"\n===== pytest suite: {suite} =====\n")
        # 透传原始 CLI 参数（此处只可能含选项，路径参数会走默认流程）
        command = [sys.executable, "-m", "pytest", suite, *map(str, config.invocation_params.args)]
        completed = subprocess.run(command, cwd=str(REPO_ROOT))
        if completed.returncode != 0:
            failures.append((suite, completed.returncode))

    if failures:
        _write("\n===== full-repo pytest summary =====\n")
        for suite, code in failures:
            _write(f"  FAILED {suite} (exit={code})\n")
        return 1
    _write("\n===== full-repo pytest: all suites passed =====\n")
    return 0
