"""Markdown 技术债报告生成 — 总览 / 规则分布 / Top 重构项 / 模块分解 / 趋势。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import config, scoring
from .models import Finding, ScanResult
from .store import GateStore

# 评分分档（经验标定，报告解读用）
_SCORE_BANDS = ((2.0, "健康"), (5.0, "需关注"), (float("inf"), "技术债快速累积期"))


def generate_report(result: ScanResult, store: GateStore) -> Path:
    """生成 Markdown 报告并返回路径。"""
    oe = result.oe_findings
    ap = result.ap_findings
    score = scoring.oew_score(oe, result.python_loc)
    prev = store.last_full_scan()
    # 环比（跳过本次自身：last_full_scan 在 save_scan 之后调用返回的是本次，
    # 故由调用方保证时序 —— run.py 先取 prev 再 save）
    lines = [
        f"# 质量门禁技术债报告",
        "",
        f"- **生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- **触发方式**: {result.trigger}（{result.mode}）",
        f"- **Git**: `{result.git_sha[:8]}` @ `{result.branch}`"
        if result.git_sha else "- **Git**: n/a",
        f"- **扫描范围**: {result.files_scanned} 文件 / {result.python_loc} 行 Python",
        "",
        "## 总览",
        "",
        "| 指标 | 本次 | 上次全量 | 环比 |",
        "|---|---|---|---|",
        f"| 技术债工时 (h) | {result.td_hours} | "
        f"{prev['td_hours'] if prev else '—'} | {_delta(result.td_hours, prev and prev['td_hours'])} |",
        f"| OE finding 数 | {len(oe)} | "
        f"{prev['n_findings'] if prev else '—'} | {_delta(len(oe), prev and prev['n_findings'])} |",
        f"| OEW 分 (分/KLoC) | {score} | — | — |",
        f"| AP 契约违规 | {len(ap)} | — | — |",
        "",
        f"> OEW 分解读：**{_score_band(score)}**（<2 健康 / 2-5 需关注 / >5 快速累积期）",
        "",
        "## 基线状态",
        "",
    ]
    lines.extend(_baseline_lines(store))
    lines.extend(_section_rules(oe))
    lines.extend(_section_top(oe))
    lines.extend(_section_modules(result, oe))
    lines.extend(_section_trend(store))
    lines.append("")
    lines.append("---")
    lines.append("*本报告由 quality_gate 自动生成；修复后基线自动标记 fixed，"
                 "误报项用 `--suppress <fingerprint> --note \"理由\"` 豁免。*")

    config.REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out = config.REPORT_DIR / f"report-{datetime.now().strftime('%Y%m%d')}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _delta(current: float, prev: float | None) -> str:
    """环比差值文本。"""
    if prev is None:
        return "—"
    diff = round(current - prev, 2)
    return f"{'+' if diff >= 0 else ''}{diff}"


def _score_band(score: float) -> str:
    """评分分档标签。"""
    for bound, label in _SCORE_BANDS:
        if score < bound:
            return label
    return "异常"


def _baseline_lines(store: GateStore) -> list[str]:
    """基线状态节。"""
    summary = store.baseline_summary()
    total = sum(summary.values()) or 1
    rows = [
        "| 状态 | 数量 | 占比 |",
        "|---|---|---|",
    ]
    for status in ("open", "fixed", "suppressed"):
        count = summary.get(status, 0)
        rows.append(f"| {status} | {count} | {count * 100 // total}% |")
    return rows + ["", f"基线演进：存量清偿率 "
                    f"{summary.get('fixed', 0) * 100 // total}%"
                    "（全部清零后可在 config 切换 OE 门禁为 block）", ""]


def _section_rules(oe: list[Finding]) -> list[str]:
    """规则分布节。"""
    rules = scoring.rule_breakdown(oe)
    if not rules:
        return ["## 规则分布", "", "无 OE finding — 过度工程信号干净。", ""]
    rows = ["## 规则分布", "", "| 规则 | 数量 |", "|---|---|"]
    rows.extend(f"| {rule} | {count} |" for rule, count in rules.items())
    return rows + [""]


def _section_top(oe: list[Finding]) -> list[str]:
    """Top 高影响重构项节。"""
    if not oe:
        return ["## Top 重构项", "", "无。", ""]
    rows = ["## Top 重构项（按预估工时降序，Top 10）", ""]
    for i, f in enumerate(scoring.top_by_effort(oe), start=1):
        rows.append(f"{i}. **`{f.file}:{f.line}`** `{f.symbol}` — {f.message}")
        rows.append(f"   - 建议: {f.fix_hint}")
        rows.append(f"   - 预估工时: {f.est_effort_h}h | severity: {f.severity.value} "
                    f"| fingerprint: `{f.fingerprint[:12]}`")
    return rows + [""]


def _section_modules(result: ScanResult, oe: list[Finding]) -> list[str]:
    """模块分解节。"""
    groups = scoring.by_module(oe)
    if not groups:
        return ["## 模块分解", "", "无。", ""]
    rows = ["## 模块分解", "", "| 模块 | findings | OEW 分* | 债务工时 (h) |", "|---|---|---|---|"]
    for module, findings in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        effort = round(sum(f.est_effort_h for f in findings), 2)
        rows.append(f"| {module} | {len(findings)} | "
                    f"{scoring.oew_score(findings, result.python_loc)} | {effort} |")
    rows.append("")
    rows.append("*OEW 分以全库 KLoC 为分母（跨模块可比）；单模块绝对值仅作趋势参考。")
    return rows + [""]


def _section_trend(store: GateStore) -> list[str]:
    """趋势节（最近 N 次全量扫描）。"""
    history = store.history(8)
    if len(history) < 2:
        return ["## 趋势", "", "尚无历史全量扫描（需 ≥2 次生成趋势）。", ""]
    rows = ["## 趋势（最近全量扫描）", "", "| 日期 | findings | 债务工时 (h) |", "|---|---|---|"]
    for row in history:
        rows.append(f"| {row['ts'][:16]} | {row['n_findings']} | {row['td_hours']} |")
    return rows + [""]