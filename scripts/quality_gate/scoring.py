"""量化模型 — severity 加权评分 / 技术债务工时 / 模块聚合 / 门禁判定。"""

from __future__ import annotations

from .models import Finding, RuleSet, SEVERITY_WEIGHT, Severity


def oew_score(findings: list[Finding], python_loc: int) -> float:
    """OEW 过度工程分：Σ(severity 权重 × 数量) / KLoC。

    分数含义（经验标定）：<2 健康 / 2-5 需关注 / >5 技术债快速累积期。
    """
    kloc = python_loc / 1000.0
    if kloc <= 0:
        return 0.0
    weight_sum = sum(SEVERITY_WEIGHT[f.severity] for f in findings
                     if f.ruleset is RuleSet.OE)
    return round(weight_sum / kloc, 2)


def severity_breakdown(findings: list[Finding]) -> dict[str, int]:
    """按 severity 统计计数。"""
    out: dict[str, int] = {s.value: 0 for s in Severity}
    for f in findings:
        out[f.severity.value] += 1
    return out


def rule_breakdown(findings: list[Finding]) -> dict[str, int]:
    """按规则统计计数（降序）。"""
    out: dict[str, int] = {}
    for f in findings:
        out[f.rule_id] = out.get(f.rule_id, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def module_of(file: str) -> str:
    """文件 → 顶级模块名（backend/api、DataPipeline、CostView、frontend 等）。"""
    parts = file.split("/")
    if not parts:
        return "<root>"
    top = parts[0]
    if top == "backend" and len(parts) > 1:
        return "backend/api" if parts[1] == "api" else top
    if top == "CostView" and len(parts) > 1:
        return "CostView/src" if parts[1] == "src" else top
    return top


def by_module(findings: list[Finding]) -> dict[str, list[Finding]]:
    """按模块聚合 Finding。"""
    out: dict[str, list[Finding]] = {}
    for f in findings:
        out.setdefault(module_of(f.file), []).append(f)
    return out


def gate_verdict(findings: list[Finding], oe_open_baseline: set[str]) -> dict:
    """门禁判定。

    返回 {ap_violations, oe_new, oe_existing}：
    - ap_violations：AP 违规（block 语义，非空即阻断）
    - oe_new：基线外新增 OE（guard 语义，非空即阻断）
    - oe_existing：存量 OE（放行）
    """
    ap_violations = [f for f in findings if f.ruleset is RuleSet.AP]
    oe = [f for f in findings if f.ruleset is RuleSet.OE]
    oe_new = [f for f in oe if f.is_new(oe_open_baseline)]
    oe_existing = [f for f in oe if not f.is_new(oe_open_baseline)]
    return {"ap_violations": ap_violations, "oe_new": oe_new, "oe_existing": oe_existing}


def top_by_effort(findings: list[Finding], limit: int = 10) -> list[Finding]:
    """按预估重构工时降序取前 N（报告 Top 列表）。"""
    ranked = sorted(findings, key=lambda f: -f.est_effort_h)
    return ranked[:limit]
