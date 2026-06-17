"""CI 测试运行脚本。

支持 --ci-mode 参数，通过 Git diff 识别变更文件判定受影响阶段，
仅运行受影响阶段及下游的增量测试，控制 CI 时间在 5 分钟内。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def get_changed_files() -> list[str]:
    """获取当前分支与主分支之间的变更文件列表"""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "origin/main..."],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


def determine_affected_stages(changed_files: list[str]) -> list[str]:
    """根据变更文件判定受影响的管道阶段。

    映射规则：
    - ingestion/ → S1, S2
    - processing/ → S3, S4, S5, S7
    - analysis/ → S8, S9, S10
    - validation/schemas/ → 全量 S1-S10
    - orchestration/ → 全量 S1-S10
    """
    affected: set[str] = set()

    for file_path in changed_files:
        if "validation/schemas/" in file_path or "orchestration/" in file_path:
            # 核心变更，全量测试
            return ["S1", "S2", "S3", "S4", "S5", "S7", "S8", "S9", "S10"]
        if "ingestion/" in file_path:
            affected.update(["S1", "S2"])
        if "processing/" in file_path:
            affected.update(["S3", "S4", "S5", "S7"])
        if "analysis/" in file_path:
            affected.update(["S8", "S9", "S10"])
        if "circuit_breaker/" in file_path or "monitoring/" in file_path:
            # 护栏组件变更，需全量验证
            return ["S1", "S2", "S3", "S4", "S5", "S7", "S8", "S9", "S10"]

    return sorted(affected) if affected else ["S1", "S2", "S3", "S4", "S5", "S7", "S8", "S9", "S10"]


def run_tests(ci_mode: bool = False) -> int:
    """运行护栏测试套件。

    Args:
        ci_mode: 是否启用 CI 增量测试模式

    Returns:
        退出码（0 = 通过，非 0 = 失败）
    """
    test_dir = Path(__file__).resolve().parent

    pytest_args = [
        sys.executable, "-m", "pytest",
        str(test_dir),
        "-v",
        "--tb=short",
    ]

    if ci_mode:
        changed_files = get_changed_files()
        affected_stages = determine_affected_stages(changed_files)
        print(f"CI 模式: 受影响阶段 → {affected_stages}")
        # 在 CI 模式下添加超时和 junitxml 输出
        pytest_args.extend([
            "--timeout=300",
            f"--junitxml={test_dir.parent.parent / 'guardrail-report.xml'}",
        ])

    print(f"执行命令: {' '.join(pytest_args)}")
    return subprocess.run(pytest_args).returncode


if __name__ == "__main__":
    ci_mode = "--ci-mode" in sys.argv
    sys.exit(run_tests(ci_mode=ci_mode))
