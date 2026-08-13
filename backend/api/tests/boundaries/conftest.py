"""边界测试配置

提供:
- violations 收集器（pytest_terminal_summary 输出；block 模式下测试直接失败）
- 模式标记 (boundary_violation)
- 项目根路径

执行模式 ENFORCEMENT_MODE:
- "record": 仅记录违规，不阻断
- "warn":   黄色告警（不阻断）
- "block":  红色阻断（检测到违规时测试失败，CI 生效）
"""
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PROJECT_ROOT.parent
VIOLATIONS_LOG = PROJECT_ROOT / "tests" / "boundaries" / ".scan_log.jsonl"
BASELINE_FILE = PROJECT_ROOT / "tests" / "boundaries" / "baseline_violations.json"

# 强制模式: "record"（仅记录）| "warn"（黄色告警）| "block"（红色阻断）
ENFORCEMENT_MODE = "block"


def pytest_configure(config):
    """注册自定义 marker + 初始化 violations 容器"""
    config._violations = []
    config._violations_by_rule = {}

    config.addinivalue_line(
        "markers",
        "boundary_violation: 标记测试函数检测到跨边界违规（block 模式下阻断）",
    )


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """在测试输出末尾显示违规清单（不改变 exit code）"""
    if not getattr(config, "_violations", None):
        return

    violations = config._violations
    by_rule = config._violations_by_rule

    if not violations:
        return

    terminalreporter.write_sep("=", "BOUNDARY VIOLATIONS", yellow=True)
    terminalreporter.write_line(f"Total: {len(violations)} | Mode: {ENFORCEMENT_MODE}")
    terminalreporter.write_line("")

    # 按规则分组
    for rule_id in sorted(by_rule.keys()):
        items = by_rule[rule_id]
        terminalreporter.write_line(f"  [{rule_id}] {len(items)} violations")
        for v in items[:5]:  # 每组最多显示 5 个
            terminalreporter.write_line(f"    {v['file']}:{v.get('line', 0)}  {v['message']}")
            if v.get("fix_hint"):
                terminalreporter.write_line(f"      Fix: {v['fix_hint']}")
        if len(items) > 5:
            terminalreporter.write_line(f"    ... and {len(items) - 5} more")
    terminalreporter.write_sep("=", "white")

    # 记录到 JSONL
    try:
        VIOLATIONS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with VIOLATIONS_LOG.open("a", encoding="utf-8") as f:
            for v in violations:
                f.write(json.dumps(v, ensure_ascii=False) + "\n")
    except OSError as e:
        terminalreporter.write_line(f"[warn] cannot write violations log: {e}")


def record_violation(config, rule_id, file, message, line=0, fix_hint=""):
    """记录一条违规（不阻断）"""
    v = {
        "rule_id": rule_id,
        "file": str(file),
        "line": line,
        "message": message,
        "fix_hint": fix_hint,
    }
    config._violations.append(v)
    config._violations_by_rule.setdefault(rule_id, []).append(v)


# ── Fixture 暴露给子目录测试 ──

@pytest.fixture
def violations_recorder(request):
    """返回一个可调用的 record_violation，绑定当前 session config"""
    config = request.config
    def _record(rule_id, file, message, line=0, fix_hint=""):
        record_violation(config, rule_id, file, message, line=line, fix_hint=fix_hint)
    return _record


@pytest.fixture
def enforcement_mode():
    """返回当前边界违规执行模式（record/warn/block）"""
    return ENFORCEMENT_MODE
