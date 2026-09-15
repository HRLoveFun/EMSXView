"""清理门禁 JSON → Markdown 摘要（CI Job Summary / PR 评论消费）。

用法::

    python scripts/cleanup.py --report --json > cleanup.json
    python scripts/cleanup/summary.py cleanup.json >> "$GITHUB_STEP_SUMMARY"

设计约束（CI 友好）：任何异常都不得让作业失败 —— 缺文件、JSON 损坏、
字段缺失一律降级为一行说明并以退出码 0 结束（摘要失败不应掩盖真实门禁结果）。
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

MAX_ROWS: int = 50          # 明细行上限（超出提示看产物）


def render(payload: dict) -> list[str]:
    """把 cleanup JSON 渲染为 Markdown 行列表。"""
    findings = payload.get("findings") or []
    cleanup = [f for f in findings if str(f.get("rule_id", "")).startswith("CL-")]
    perf = [f for f in findings if str(f.get("rule_id", "")).startswith("PF-")]
    lines = [
        "| 指标 | 数量 |",
        "|---|---|",
        "| 扫描文件 | %s |" % payload.get("files_scanned", "?"),
        "| 清理项 CL-xx | **%d** |" % len(cleanup),
        "| 性能项 PF-xx | %d |" % len(perf),
        "| 扫描耗时 | %ss |" % payload.get("duration_s", "?"),
        "",
    ]
    if not cleanup:
        lines.append("✅ 清理项为 0（无冗余代码信号）")
        return lines
    lines += ["### 清理项明细", "", "| 规则 | 位置 | 符号 | 说明 |", "|---|---|---|---|"]
    for item in cleanup[:MAX_ROWS]:
        lines.append("| %s | `%s:%s` | `%s` | %s |" % (
            item.get("rule_id", "?"), item.get("file", "?"), item.get("line", "?"),
            item.get("symbol", "?"), item.get("message", "")))
    if len(cleanup) > MAX_ROWS:
        lines += ["", "（其余 %d 项见报告产物）" % (len(cleanup) - MAX_ROWS)]
    return lines


def _header() -> list[str]:
    return [
        "> 清理项（CL-xx）为删除**候选**，删除决策需人工确认；",
        "> 性能项（PF-xx）为静态候选，须经 profiler 实测后才算缺陷。",
        "",
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：读取 JSON 路径并打印 Markdown 摘要（永不失败）。"""
    _force_utf8_stdout()
    args = argv if argv is not None else sys.argv[1:]
    path = Path(args[0]) if args else Path("cleanup.json")
    payload = _load(path)
    if payload is None:
        print("（未读取到 %s：扫描可能失败，见作业日志）" % path)
        return 0
    print("\n".join(_header() + render(payload)))
    return 0


def _load(path: Path) -> dict | None:
    """读取并解析 JSON；失败返回 None。"""
    try:
        return json.loads(io.open(path, encoding="utf-8").read())
    except (OSError, ValueError):
        return None


def _force_utf8_stdout() -> None:
    """Windows 控制台（cp1252）下强制 UTF-8，避免中文输出 UnicodeEncodeError。"""
    if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
