"""AP 适配层 — 包装既有 ``audit_*.py`` 审计脚本为统一 Finding。

零改动零回归：底层子进程调用脚本的 ``--json`` 输出，仅归一化结果结构。
脚本执行失败（环境异常）时抛出 RuntimeError —— AP 是契约防线而非监测，
保持与既有 pre-commit 一致的严格语义（失败即阻断，不 fail-open）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from ..ast_utils import make_fingerprint
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

# 审计脚本 → 规则 ID（退出码 0/1 均为正常执行；1 表示有违规）
_AP_SCRIPTS: list[tuple[str, str]] = [
    ("audit_cross_imports.py", "AP-01"),
    ("audit_underscore_access.py", "AP-08"),
    ("audit_db_paths.py", "AP-04"),
]

# 各规则的修复建议（与 docs/spec/anti-patterns.md 对齐）
_FIX_HINTS: dict[str, str] = {
    "AP-01": "前端跨模块改走 navigateTo + useHandoffContracts；后端跨域改走 platform_data 适配器",
    "AP-08": "改用适配器公开 API（无下划线前缀）",
    "AP-04": "改用 DataPipeline.config.Config 中的路径属性",
}


def detect(ctx: ScanContext) -> list[Finding]:
    """执行全部 AP 审计脚本，归一化违规为 Finding 列表。"""
    findings: list[Finding] = []
    for script_name, rule_id in _AP_SCRIPTS:
        script_path = ctx.root / "scripts" / script_name
        findings.extend(_run_audit_script(script_path, rule_id))
    return findings


def _run_audit_script(script_path: Path, rule_id: str) -> list[Finding]:
    """子进程调用单个审计脚本，解析 JSON 违规。"""
    if not script_path.exists():
        raise RuntimeError(f"AP 审计脚本不存在: {script_path}")
    try:
        proc = subprocess.run(
            [sys.executable, str(script_path), "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"AP 审计脚本超时: {script_path.name}") from exc

    if proc.returncode not in (0, 1):
        raise RuntimeError(
            f"AP 审计脚本执行失败 ({script_path.name}, exit={proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    try:
        violations = json.loads(proc.stdout).get("violations", [])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"AP 审计脚本输出无法解析: {script_path.name}") from exc
    return [_to_finding(rule_id, v) for v in violations]


def _to_finding(rule_id: str, violation: dict) -> Finding:
    """违规字典 → 统一 Finding。"""
    file = str(violation.get("path", ""))
    line = int(violation.get("line", 0) or 0)
    symbol = str(
        violation.get("import_name")
        or violation.get("snippet")
        or violation.get("literal")
        or ""
    )
    message = _build_message(rule_id, violation, symbol)
    return Finding(
        rule_id=rule_id,
        ruleset=RuleSet.AP,
        severity=Severity.HIGH,
        file=file,
        line=line,
        symbol=symbol,
        message=message,
        fix_hint=_FIX_HINTS.get(rule_id, "参见 docs/spec/anti-patterns.md"),
        fingerprint=make_fingerprint(rule_id, file, str(line), symbol),
        est_effort_h=0.0,
    )


def _build_message(rule_id: str, violation: dict, symbol: str) -> str:
    """按规则构造中文问题描述。"""
    if rule_id == "AP-01":
        return (
            f"跨模块 deep import: {symbol}"
            f"（模块 {violation.get('module')} 禁止 {violation.get('forbidden')}*）"
        )
    if rule_id == "AP-08":
        return f"跨域访问适配器私有方法: {symbol}"
    return f"DB 路径硬编码: '{symbol}'"
