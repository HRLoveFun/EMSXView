"""CLI 核心 — 全量 / 增量 / 报告 / 豁免四模式。

退出码语义：0=通过（或 fail-open）；1=门禁阻断。
AP 检测器异常 → 阻断（契约防线不 fail-open）；OE 检测器异常 → 告警跳过。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from . import config
from .context import (
    ScanContext,
    collect_all_python_files,
    collect_frontend_files,
    collect_python_files,
)
from .detectors import FULL_DETECTORS, STAGED_DETECTORS, ap_adapter
from .models import Finding, RuleSet, ScanResult
from .reporter import generate_report
from .scoring import gate_verdict
from .store import GateStore


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = _parse_args(argv)
    if args.suppress:
        return _run_suppress(args)
    return _run_scan(args)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """参数解析。"""
    parser = argparse.ArgumentParser(
        prog="quality_gate",
        description="EMSXView 质量门禁 — AP 契约违规 + OE 过度工程监测",
    )
    parser.add_argument("--staged", action="store_true",
                        help="增量模式：从 stdin 读取暂存文件列表（pre-commit 用）")
    parser.add_argument("--report", action="store_true",
                        help="全量扫描并生成 Markdown 技术债报告")
    parser.add_argument("--ruleset", choices=["ap", "oe"],
                        help="仅运行指定规则集")
    parser.add_argument("--quiet", action="store_true",
                        help="精简输出（只报阻断项与计数）")
    parser.add_argument("--suppress", metavar="FINGERPRINT",
                        help="人工豁免指定 finding（配合 --note）")
    parser.add_argument("--note", default="人工豁免",
                        help="豁免理由（配合 --suppress）")
    return parser.parse_args(argv)


# ── 豁免模式 ──────────────────────────────────────────────────────

def _run_suppress(args: argparse.Namespace) -> int:
    """人工豁免误报。"""
    store = GateStore(config.DB_PATH)
    try:
        if store.suppress(args.suppress, args.note):
            print(f"[quality-gate] 已豁免 {args.suppress}（{args.note}）")
            return 0
        print(f"[quality-gate] 豁免失败：fingerprint 不存在（{args.suppress}）")
        return 1
    finally:
        store.close()


# ── 扫描模式 ──────────────────────────────────────────────────────

def _run_scan(args: argparse.Namespace) -> int:
    """执行扫描 + 基线维护 + 门禁判定。"""
    mode = "staged" if args.staged else "full"
    trigger = "commit" if args.staged else "manual"
    _force_utf8_stdout()

    ctx = _build_context(mode)
    detectors = _select_detectors(mode, args.ruleset)
    start = time.monotonic()

    findings: list[Finding] = []
    failures: list[str] = []
    for detector in detectors:
        if not ctx.in_budget():
            failures.append(f"时间预算耗尽，跳过 {detector.__module__.rsplit('.', 1)[-1]}")
            continue
        try:
            findings.extend(detector(ctx))
        except Exception as exc:  # noqa: BLE001 — OE fail-open / AP 阻断由调用方区分
            if detector.__module__.endswith("ap_adapter"):
                raise RuntimeError(f"AP 检测器异常（契约防线，不 fail-open）: {exc}") from exc
            failures.append(f"{detector.__module__.rsplit('.', 1)[-1]}: {exc}")

    store = GateStore(config.DB_PATH)
    try:
        suppressed = store.load_suppressed()
        findings = [f for f in findings if f.fingerprint not in suppressed]
        result = _build_result(trigger, mode, ctx, findings,
                               round(time.monotonic() - start, 2))
        prev = store.last_full_scan()
        # 先加载基线快照用于门禁判定（必须在 upsert 之前，否则新增项被误判为存量）
        oe_open = store.load_open_fingerprints("oe")
        store.save_scan(result)
        store.upsert_baseline(findings)
        # 仅完整扫描（full + 全规则集）才标记清偿 — 部分扫描覆盖面不完整
        fixed_hint = _maintain_baseline(store, mode, args.ruleset, findings, ctx)
        verdict = gate_verdict(result.findings, oe_open)
        report_path = generate_report(result, store) if (args.report and mode == "full") else None
        _output_verdict(result, verdict, prev, args, failures, fixed_hint, report_path)
        blocking = verdict["ap_violations"] + verdict["oe_new"]
        return 1 if blocking else 0
    finally:
        store.close()


def _build_context(mode: str) -> ScanContext:
    """构建扫描上下文（full/staged 差异 = 判定对象文件集）。"""
    root = config.PROJECT_ROOT
    if mode == "full":
        python_files = collect_python_files(root, config.PYTHON_SCAN_ROOTS)
        frontend_files = collect_frontend_files(root)
    else:
        staged = _read_staged_files(root)
        python_files = [p for p in staged if p.suffix == ".py"]
        frontend_files = [p for p in staged if p.suffix in (".ts", ".tsx")]
    return ScanContext(
        root=root,
        mode=mode,
        python_files=python_files,
        frontend_files=frontend_files,
        all_python_files=collect_all_python_files(root),
        all_frontend_files=collect_frontend_files(root),
        deadline=time.monotonic() + config.STAGED_TIME_BUDGET_S if mode == "staged" else None,
    )


def _read_staged_files(root: Path) -> list[Path]:
    """从 stdin 读取暂存文件列表（每行一个仓库相对路径）。"""
    out: list[Path] = []
    # 容错：Windows PowerShell echo 可能注入 UTF-8 BOM（0xef 0xbb 0xbf），
    # 在 cp1252 文本模式下未解码为 \ufeff，需按字节剥离
    data = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        path = root / line
        if path.exists() and path.suffix in (".py", ".ts", ".tsx"):
            out.append(path)
    return out


def _select_detectors(mode: str, ruleset: str | None) -> list:
    """按模式与规则集过滤检测器（AP 适配层永不被过滤掉 — 契约防线）。"""
    detectors = FULL_DETECTORS if mode == "full" else STAGED_DETECTORS
    if ruleset is None:
        return detectors
    if ruleset == "ap":
        return [ap_adapter.detect]
    return [d for d in detectors if d is not ap_adapter.detect]


def _build_result(trigger: str, mode: str, ctx: ScanContext,
                  findings: list[Finding], duration: float) -> ScanResult:
    """组装扫描结果。"""
    sha, branch = _git_info()
    python_loc = sum(
        len((ctx.text(p) or "").splitlines()) for p in ctx.python_files)
    return ScanResult(
        trigger=trigger, mode=mode, git_sha=sha, branch=branch,
        python_loc=python_loc,
        files_scanned=len(ctx.python_files) + len(ctx.frontend_files),
        duration_s=duration, findings=findings,
    )


def _git_info() -> tuple[str, str]:
    """当前 git SHA 与分支（失败返回空串）。"""
    try:
        sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                                capture_output=True, text=True, timeout=10).stdout.strip()
        return sha, branch
    except (subprocess.SubprocessError, OSError):
        return "", ""


def _maintain_baseline(store: GateStore, mode: str, ruleset: str | None,
                       findings: list[Finding], ctx: ScanContext) -> list[str]:
    """基线维护：完整扫描标记清偿；staged 输出修复提示。返回修复提示行。"""
    if mode == "full" and ruleset is None:
        fixed = store.mark_fixed_missing({f.fingerprint for f in findings})
        return [f"[quality-gate] 存量清偿：{fixed} 项标记 fixed"] if fixed else []
    if mode == "full":
        return []
    # staged：staged 文件内 open 基线项本轮未复现 → 大概率已修复（正向反馈）
    staged_files = {
        p.relative_to(ctx.root).as_posix() for p in ctx.python_files + ctx.frontend_files}
    open_map = store.open_baseline_for_files(staged_files)
    seen = {f.fingerprint for f in findings}
    repaired = [fp for fp in open_map if fp not in seen]
    return [f"[quality-gate] ✔ 可能已修复 {len(repaired)} 项存量问题"
            "（全量扫描后正式标记 fixed）"] if repaired else []


# ── 输出与退出码 ──────────────────────────────────────────────────

def _output_verdict(result: ScanResult, verdict: dict, prev: dict | None,
                    args: argparse.Namespace, failures: list[str],
                    fixed_hint: list[str], report_path: Path | None) -> None:
    """输出门禁判定（终端格式，含修复建议）。"""
    ap_n, new_n, old_n = (len(verdict["ap_violations"]),
                          len(verdict["oe_new"]), len(verdict["oe_existing"]))
    print(f"[quality-gate] {result.mode} 扫描完成（{result.duration_s}s，"
          f"{result.files_scanned} 文件）: AP 违规 {ap_n} / OE 新增 {new_n} / 存量 {old_n}")
    for failure in failures:
        print(f"[quality-gate] [warn] 检测器异常（fail-open 跳过）: {failure}")
    for hint in fixed_hint:
        print(hint)

    blocking = verdict["ap_violations"] + verdict["oe_new"]
    for f in blocking:
        _print_finding("✘", f)
    if not args.quiet:
        for f in verdict["oe_existing"]:
            _print_finding("·", f)
    if blocking:
        print("[quality-gate] 阻断：存在 AP 契约违规或新增过度工程信号，"
              "请按上方建议修复后重新提交（存量问题未阻断）")
    if report_path is not None:
        print(f"[quality-gate] 报告已生成: {report_path}")
    if prev is not None and result.mode == "full":
        print(f"[quality-gate] 环比上次全量（{prev['ts'][:16]}）: findings "
              f"{prev['n_findings']} → {len(result.findings)}，"
              f"债务 {prev['td_hours']}h → {result.td_hours}h")


def _print_finding(marker: str, f: Finding) -> None:
    """单条 finding 终端输出。"""
    print(f"{marker} [{f.rule_id}] {f.file}:{f.line} {f.symbol} — {f.message}")
    print(f"  ↳ {f.fix_hint}")


def _force_utf8_stdout() -> None:
    """Windows 控制台（cp1252）下强制 UTF-8，避免中文输出 UnicodeEncodeError。"""
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
