"""清理门禁 CLI — 扫描 / 规则集过滤 / 报告 / 豁免 / 严格模式。

退出码：``0`` = 建议性完成（默认不阻断）；``1`` = ``--strict`` 且存在基线外新增项。
检测器异常一律 fail-open —— 启发式规则的故障不得阻断正常开发。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from scripts.quality_gate import config as qg_config
from scripts.quality_gate.context import (
    ScanContext,
    collect_all_python_files,
    collect_frontend_files,
    collect_python_files,
)
from scripts.quality_gate.models import Finding, ScanResult
from scripts.quality_gate.store import GateStore

from . import config, reporter
from .detectors import CL_DETECTORS, FULL_DETECTORS, PF_DETECTORS

_RULESETS = {"all": FULL_DETECTORS, "cl": CL_DETECTORS, "pf": PF_DETECTORS}


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。"""
    args = _parse_args(argv)
    _force_utf8_stdout()
    if args.suppress:
        return _run_suppress(args)
    return _run_scan(args)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """参数解析。"""
    parser = argparse.ArgumentParser(
        prog="cleanup",
        description="EMSXView 代码清理与性能热点门禁（CL-xx / PF-xx）",
    )
    parser.add_argument("--staged", action="store_true",
                        help="增量模式：从 stdin 读取暂存文件列表（pre-commit 用）")
    parser.add_argument("--ruleset", choices=sorted(_RULESETS), default="all",
                        help="规则集：all=清理+性能 / cl=仅清理 / pf=仅性能")
    parser.add_argument("--report", action="store_true",
                        help="全量扫描并生成 Markdown 报告")
    parser.add_argument("--json", action="store_true",
                        help="以 JSON 输出结果（CI / 仪表盘消费）")
    parser.add_argument("--strict", action="store_true",
                        help="存在基线外新增项时返回退出码 1（默认仅提示）")
    parser.add_argument("--quiet", action="store_true",
                        help="精简输出（只列 high/medium 新增项）")
    parser.add_argument("--suppress", metavar="FINGERPRINT",
                        help="人工豁免指定 finding（配合 --note）")
    parser.add_argument("--note", default="人工豁免", help="豁免理由（配合 --suppress）")
    return parser.parse_args(argv)


# ── 豁免模式 ──────────────────────────────────────────────────────

def _run_suppress(args: argparse.Namespace) -> int:
    """人工豁免误报。"""
    store = GateStore(config.DB_PATH)
    try:
        if store.suppress(args.suppress, args.note):
            print(f"[cleanup] 已豁免 {args.suppress}（{args.note}）")
            return 0
        print(f"[cleanup] 豁免失败：fingerprint 不存在（{args.suppress}）")
        return 1
    finally:
        store.close()


# ── 扫描模式 ──────────────────────────────────────────────────────

def _run_scan(args: argparse.Namespace) -> int:
    """执行扫描 + 基线维护 + 输出。"""
    mode = "staged" if args.staged else "full"
    trigger = "commit" if args.staged else "manual"
    ctx = _build_context(mode)
    start = time.monotonic()
    findings, failures = _run_detectors(_RULESETS[args.ruleset], ctx)

    store = GateStore(config.DB_PATH)
    try:
        findings = _drop_suppressed(store, findings)
        prev = store.last_full_scan()
        known = store.load_open_fingerprints("oe")
        result = _build_result(trigger, mode, ctx, findings,
                              round(time.monotonic() - start, 2))
        if _is_full_coverage(mode, args.ruleset):
            # 规则集过滤 / staged 属于部分覆盖，写入趋势库会让「环比上次全量」
            # 与报告趋势表出现虚假的 0 项基准（同 _maintain_baseline 的口径）。
            store.save_scan(result)
        store.upsert_baseline(findings)
        fixed = _maintain_baseline(store, mode, args.ruleset, findings)
        new_ids = {f.fingerprint for f in findings if f.is_new(known)}
        report_path = reporter.generate_report(result, store, new_ids) \
            if (args.report and mode == "full") else None
        if args.json:
            print(reporter.render_json(result, new_ids))
        else:
            _output(result, findings, new_ids, args, failures, fixed, report_path, prev)
        return 1 if ((args.strict or config.STRICT_ENFORCEMENT) and new_ids) else 0
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
        deadline=time.monotonic() + qg_config.STAGED_TIME_BUDGET_S if mode == "staged" else None,
    )


def _read_staged_files(root: Path) -> list[Path]:
    """从 stdin 读取暂存文件列表（每行一个仓库相对路径）。"""
    data = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    out: list[Path] = []
    for line in data.splitlines():
        line = line.strip()
        path = root / line
        if line and path.exists() and path.suffix in (".py", ".ts", ".tsx"):
            out.append(path)
    return out


def _run_detectors(detectors: list, ctx: ScanContext) -> tuple[list[Finding], list[str]]:
    """依次执行检测器（超预算跳过，异常 fail-open）。"""
    findings: list[Finding] = []
    failures: list[str] = []
    for detector in detectors:
        if not ctx.in_budget():
            failures.append(f"时间预算耗尽，跳过 {detector.__module__.rsplit('.', 1)[-1]}")
            continue
        try:
            findings.extend(detector(ctx))
        except Exception as exc:  # noqa: BLE001 — 启发式规则一律 fail-open
            failures.append(f"{detector.__module__.rsplit('.', 1)[-1]}: {exc}")
    return findings, failures


def _drop_suppressed(store: GateStore, findings: list[Finding]) -> list[Finding]:
    """剔除人工豁免项。"""
    suppressed = store.load_suppressed()
    return [f for f in findings if f.fingerprint not in suppressed]


def _is_full_coverage(mode: str, ruleset: str) -> bool:
    """是否为「全量 + 全规则集」的完整覆盖扫描。

    规则集过滤与 staged 均为部分覆盖：其结果不得进入趋势库，
    否则「环比上次全量」与报告趋势表会出现虚假基准。
    """
    return mode == "full" and ruleset == "all"


def _maintain_baseline(store: GateStore, mode: str, ruleset: str,
                       findings: list[Finding]) -> int:
    """完整扫描标记清偿；部分扫描（规则集过滤）覆盖面不全故跳过。"""
    if not _is_full_coverage(mode, ruleset):
        return 0
    return store.mark_fixed_missing({f.fingerprint for f in findings})


def _build_result(trigger: str, mode: str, ctx: ScanContext,
                  findings: list[Finding], duration: float) -> ScanResult:
    """组装扫描结果。"""
    sha, branch = _git_info()
    python_loc = sum(len((ctx.text(p) or "").splitlines()) for p in ctx.python_files)
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


# ── 输出 ──────────────────────────────────────────────────────────

def _output(result: ScanResult, findings: list[Finding], new_ids: set[str],
            args: argparse.Namespace, failures: list[str], fixed: int,
            report_path: Path | None, prev: dict | None) -> None:
    """终端输出（计数 + 明细 + 报告路径 + 环比）。"""
    cleanup = [f for f in findings if f.rule_id.startswith("CL-")]
    perf = [f for f in findings if f.rule_id.startswith("PF-")]
    print(f"[cleanup] {result.mode} 扫描完成（{result.duration_s}s，"
          f"{result.files_scanned} 文件）: 清理项 {len(cleanup)} / 性能项 {len(perf)} / "
          f"新增 {len(new_ids)} / 存量 {len(findings) - len(new_ids)}")
    for failure in failures:
        print(f"[cleanup] [warn] 检测器异常（fail-open 跳过）: {failure}")
    if fixed:
        print(f"[cleanup] 存量清偿：{fixed} 项标记 fixed")
    for finding in _visible(findings, new_ids, args.quiet):
        marker = "✘" if finding.fingerprint in new_ids else "·"
        print(f"{marker} [{finding.rule_id}] {finding.file}:{finding.line} "
              f"{finding.symbol} — {finding.message}")
        print(f"  ↳ {finding.fix_hint}")
    print("[cleanup] 清理项默认不阻断（删除决策需人工确认）；"
          "CI 强门禁可加 --strict")
    if report_path is not None:
        print(f"[cleanup] 报告已生成: {report_path}")
    if prev is not None and result.mode == "full":
        print(f"[cleanup] 环比上次全量（{prev['ts'][:16]}）: findings "
              f"{prev['n_findings']} → {len(findings)}")


def _visible(findings: list[Finding], new_ids: set[str], quiet: bool) -> list[Finding]:
    """终端展示集合（quiet 模式只显示新增且非 low）。"""
    if not quiet:
        return findings
    return [f for f in findings
            if f.fingerprint in new_ids and f.severity.value != "low"]


def _force_utf8_stdout() -> None:
    """Windows 控制台（cp1252）下强制 UTF-8，避免中文输出 UnicodeEncodeError。"""
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")
