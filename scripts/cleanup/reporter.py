"""清理报告生成 — Markdown（人读）与 JSON（工具链消费）。

报告分区对应 skill 工作流的两大目标：
- 清理行动清单（CL-xx）：可删除/可收敛的冗余
- 性能优化清单（PF-xx）：需 profiler 复核的性能候选
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from scripts.quality_gate import scoring
from scripts.quality_gate.models import Finding, ScanResult
from scripts.quality_gate.store import GateStore

from . import config

_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def generate_report(result: ScanResult, store: GateStore, new_ids: set[str]) -> Path:
    """生成 Markdown 报告并返回路径。"""
    cleanup, perf, hotspot = _split(result.findings)
    lines: list[str] = []
    lines.extend(_header(result))
    lines.extend(_overview(result, cleanup, perf, hotspot, len(new_ids)))
    lines.extend(_baseline(store))
    lines.extend(_rule_distribution(result.findings))
    lines.extend(_action_section("清理行动清单", cleanup,
                                "删除/收敛前必须确认无动态引用（见 skill「安全协议」），分批提交。"))
    lines.extend(_action_section("性能优化清单", perf,
                                "命中项为静态候选，先用 py-spy / cProfile / EXPLAIN QUERY PLAN 实测再改。"))
    lines.extend(_action_section("热点候选（非缺陷）", hotspot,
                                "按热度分排序，仅代表实测优先级，不代表存在缺陷。"))
    lines.extend(_modules(result))
    lines.extend(_trend(store))
    lines.append("---")
    lines.append("*本报告由 `scripts/cleanup` 生成；误报用 "
                 "`python scripts/cleanup.py --suppress <fingerprint> --note \"理由\"` 豁免。*")

    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORT_DIR / f"report-{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def render_json(result: ScanResult, new_ids: set[str]) -> str:
    """机器可读结果（CI / 仪表盘消费）。"""
    payload = {
        "trigger": result.trigger,
        "mode": result.mode,
        "git_sha": result.git_sha,
        "branch": result.branch,
        "files_scanned": result.files_scanned,
        "python_loc": result.python_loc,
        "duration_s": result.duration_s,
        "n_findings": len(result.findings),
        "n_new": len(new_ids),
        "td_hours": result.td_hours,
        "findings": [
            {
                "rule_id": f.rule_id,
                "title": config.RULE_TITLES.get(f.rule_id, f.rule_id),
                "severity": f.severity.value,
                "file": f.file,
                "line": f.line,
                "symbol": f.symbol,
                "message": f.message,
                "fix_hint": f.fix_hint,
                "fingerprint": f.fingerprint,
                "is_new": f.fingerprint in new_ids,
                "est_effort_h": f.est_effort_h,
            }
            for f in _sorted_findings(result.findings)
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ── 分区 ──────────────────────────────────────────────────────────

def _split(findings: list[Finding]) -> tuple[list[Finding], list[Finding], list[Finding]]:
    """拆分为 清理 / 性能 / 热点候选 三组。"""
    hotspot = [f for f in findings if f.rule_id == "PF-06"]
    rest = [f for f in findings if f.rule_id != "PF-06"]
    cleanup = [f for f in rest if f.rule_id.startswith("CL-")]
    perf = [f for f in rest if f.rule_id.startswith("PF-")]
    return cleanup, perf, hotspot


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    """按 severity → 规则 → 文件 排序。"""
    return sorted(findings, key=lambda f: (_SEVERITY_ORDER.get(f.severity.value, 9),
                                           f.rule_id, f.file, f.line))


def _header(result: ScanResult) -> list[str]:
    """报告头。"""
    git = f"`{result.git_sha[:8]}` @ `{result.branch}`" if result.git_sha else "n/a"
    return [
        "# 代码清理与性能热点报告",
        "",
        f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **触发方式**: {result.trigger}（{result.mode}）",
        f"- **Git**: {git}",
        f"- **扫描范围**: {result.files_scanned} 文件 / {result.python_loc} 行 Python",
        "",
    ]


def _overview(result: ScanResult, cleanup: list[Finding], perf: list[Finding],
              hotspot: list[Finding], n_new: int) -> list[str]:
    """总览节。"""
    return [
        "## 总览",
        "",
        "| 指标 | 数量 |",
        "|---|---|",
        f"| 清理项（CL-xx） | {len(cleanup)} |",
        f"| 性能项（PF-01~05/07/08） | {len(perf)} |",
        f"| 热点候选（PF-06） | {len(hotspot)} |",
        f"| 本轮新增（基线外） | {n_new} |",
        f"| 预估工时合计 (h) | {result.td_hours} |",
        "",
    ]


def _baseline(store: GateStore) -> list[str]:
    """基线状态节。"""
    summary = store.baseline_summary()
    total = sum(summary.values()) or 1
    rows = ["## 基线状态", "", "| 状态 | 数量 | 占比 |", "|---|---|---|"]
    for status in ("open", "fixed", "suppressed"):
        count = summary.get(status, 0)
        rows.append(f"| {status} | {count} | {count * 100 // total}% |")
    rows.extend(["", f"存量清偿率 {summary.get('fixed', 0) * 100 // total}%", ""])
    return rows


def _rule_distribution(findings: list[Finding]) -> list[str]:
    """规则分布节。"""
    rows = ["## 规则分布", "", "| 规则 | 含义 | 数量 |", "|---|---|---|"]
    for rule_id, count in scoring.rule_breakdown(findings).items():
        rows.append(f"| {rule_id} | {config.RULE_TITLES.get(rule_id, '')} | {count} |")
    return rows + [""]


def _action_section(title: str, findings: list[Finding], note: str) -> list[str]:
    """行动清单节（按规则分组，逐条含位置 / 建议 / 指纹）。"""
    rows = [f"## {title}", "", f"> {note}", ""]
    if not findings:
        return rows + ["无。", ""]
    for rule_id in sorted({f.rule_id for f in findings}):
        group = [f for f in _sorted_findings(findings) if f.rule_id == rule_id]
        rows.extend([f"### {rule_id} {config.RULE_TITLES.get(rule_id, '')}（{len(group)}）", ""])
        for f in group:
            rows.append(f"- **`{f.file}:{f.line}`** `{f.symbol}` — {f.message}")
            rows.append(f"  - 建议: {f.fix_hint}")
            rows.append(f"  - severity: {f.severity.value} | 工时: {f.est_effort_h}h | "
                        f"指纹: `{f.fingerprint[:12]}`")
        rows.append("")
    return rows


def _modules(result: ScanResult) -> list[str]:
    """模块分解节。"""
    groups = scoring.by_module(result.findings)
    if not groups:
        return ["## 模块分解", "", "无。", ""]
    rows = ["## 模块分解", "", "| 模块 | 发现数 | 工时 (h) |", "|---|---|---|"]
    for module, findings in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        effort = round(sum(f.est_effort_h for f in findings), 2)
        rows.append(f"| {module} | {len(findings)} | {effort} |")
    return rows + [""]


def _trend(store: GateStore) -> list[str]:
    """趋势节。"""
    history = store.history(8)
    if len(history) < 2:
        return ["## 趋势", "", "尚无历史全量扫描（需 ≥2 次生成趋势）。", ""]
    rows = ["## 趋势（最近全量扫描）", "", "| 日期 | findings | 工时 (h) |", "|---|---|---|"]
    for row in history:
        rows.append(f"| {row['ts'][:16]} | {row['n_findings']} | {row['td_hours']} |")
    return rows + [""]
