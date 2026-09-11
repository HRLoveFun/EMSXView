"""CLI 入口 smoke test — 断言 python -m CostView.src 可用且退出码语义正确。

对应 README §4.2「CLI 入口失效」整改：__main__.py 恢复后由本测试锁定。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

# 仓库根（CostView 的上级目录）
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """在仓库根以当前解释器运行 CLI 子进程。

    encoding="utf-8"：CLI 强制 UTF-8 输出（Windows 控制台默认 cp1252
    会 UnicodeDecodeError），父进程须按同一编码解码。
    """
    return subprocess.run(
        [sys.executable, "-m", "CostView.src", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )


class TestCliEntrypoint:
    def test_help_exits_zero(self):
        """--help 正常返回 0，且 usage 含 prog 名称。"""
        proc = _run_cli("--help")
        assert proc.returncode == 0, proc.stderr
        assert "CostView.src" in proc.stdout
        assert "--query" in proc.stdout

    def test_invalid_query_exits_nonzero(self):
        """非法 --query 由 argparse 拒绝（退出码 2，usage 错误）。"""
        proc = _run_cli("--query", "nonexistent")
        assert proc.returncode != 0

    @pytest.mark.parametrize("query", [
        "fills", "raw-fills", "log", "order-log", "orders", "tickers", "summary",
    ])
    def test_all_queries_accepted(self, query: str):
        """所有声明的 query 类型均被 argparse 接受（不因选择项非法而失败）。"""
        proc = _run_cli("--query", query, "--help")
        # --help 优先于校验，返回 0 即证明 query 值合法被接受
        assert proc.returncode == 0
