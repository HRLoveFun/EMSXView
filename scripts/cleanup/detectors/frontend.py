"""前端清理与性能检测器 — CL-10 不可达文件 / PF-07 渲染热点 / PF-08 Provider 未 memo。

CL-10 做「多入口可达性」：本项目前端有 4 个真实入口（主应用 `src/main.tsx` +
`src/standalone/{execution,costview,marketview}/main.tsx`）与测试装配文件，
从入口 BFS 得可达集，未达文件即零引用候选。
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.quality_gate import config as qg_config
from scripts.quality_gate.ast_utils import (
    dir_of,
    make_fingerprint,
    normalize_path,
    rel_posix,
)
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config

# 说明符提取：`from 'x'` 覆盖多行 import；裸 import 与动态 import 单列
_RE_FROM = re.compile(r"""from\s+['"]([^'"]+)['"]""")
_RE_BARE_IMPORT = re.compile(r"""^\s*import\s+['"]([^'"]+)['"]""", re.MULTILINE)
_RE_DYNAMIC_IMPORT = re.compile(r"""import\(\s*['"]([^'"]+)['"]\s*\)""")
_EXT_PROBES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")


def detect_cleanup(ctx: ScanContext) -> list[Finding]:
    """CL-10 前端不可达文件。"""
    src_files = {p.as_posix() for p in ctx.all_frontend_files}
    if not src_files:
        return []
    edges = {p.as_posix(): _resolve_specs(ctx, p, src_files)
             for p in ctx.all_frontend_files}
    reachable = _reachable({p.as_posix() for p in ctx.all_frontend_files if _is_entry(p)}, edges)
    findings: list[Finding] = []
    for path in ctx.frontend_files:
        src = path.as_posix()
        if src in reachable or _is_skipped(path):
            continue
        rel = rel_posix(path, ctx.root)
        findings.append(_mk(
            "CL-10", rel, 1, path.stem, rel,
            "前端不可达文件：从 4 个构建入口 BFS 均未触达（零引用）",
            "确认无运行时动态 import / HTML 直接引用后删除；"
            "确为预留页面请接入模块注册表或加 suppressed 注明",
            Severity.MEDIUM, 0.5))
    return findings


# ── 前端 import 图 ────────────────────────────────────────────────

def _is_entry(path: Path) -> bool:
    """前端图入口：main/index 约定名、standalone 子树、类型声明、测试件。"""
    name = path.name
    if name in config.FRONTEND_ENTRY_NAMES or name.endswith(".d.ts"):
        return True
    if _is_test(path):
        return True
    return "standalone" in path.parts


def _is_test(path: Path) -> bool:
    """测试文件（其主体由测试运行器直接加载，属入口）。"""
    return ".test." in path.name or ".spec." in path.name


def _is_skipped(path: Path) -> bool:
    """豁免文件：类型声明 / 测试件 / 依赖目录。"""
    return path.name.endswith(".d.ts") or _is_test(path) or \
        any(part in config.EXEMPT_DIR_PARTS for part in path.parts)


def _resolve_specs(ctx: ScanContext, path: Path, file_set: set[str]) -> set[str]:
    """单文件所有本地说明符解析出的目标文件集合。"""
    text = ctx.text(path)
    if not text:
        return set()
    source = path.as_posix()
    specs = _RE_FROM.findall(text) + _RE_BARE_IMPORT.findall(text) \
        + _RE_DYNAMIC_IMPORT.findall(text)
    targets = {_resolve_spec(ctx, spec, source, file_set) for spec in specs}
    return {target for target in targets if target}


def _resolve_spec(ctx: ScanContext, spec: str, importer: str, file_set: set[str]) -> str | None:
    """说明符 → 文件（相对路径 / 别名 + 扩展名补全；npm 包返回 None）。"""
    base = _base_path(ctx, spec, importer)
    if base is None:
        return None
    for ext in _EXT_PROBES:
        probe = base + ext if ext else base
        if probe in file_set:
            return probe
    return None


def _base_path(ctx: ScanContext, spec: str, importer: str) -> str | None:
    """说明符的候选路径基址（未补扩展名）。"""
    if spec.startswith("."):
        return normalize_path(f"{dir_of(importer)}/{spec}")
    if not spec.startswith("@"):
        return None
    prefix = spec.split("/")[0]
    mapped = qg_config.FRONTEND_ALIASES.get(prefix)
    if mapped is None:
        return None
    rest = spec[len(prefix):].lstrip("/")
    rel = f"{mapped}/{rest}" if mapped and rest else (mapped or rest)
    return normalize_path(str(ctx.root / qg_config.FRONTEND_SCAN_ROOT / rel))


def _reachable(entries: set[str], edges: dict[str, set[str]]) -> set[str]:
    """从入口集合 BFS 求可达文件集。"""
    seen = set(entries)
    queue = list(entries)
    while queue:
        for target in edges.get(queue.pop(), ()):
            if target not in seen:
                seen.add(target)
                queue.append(target)
    return seen


# ── PF-07 / PF-08 前端性能 ───────────────────────────────────────

def detect_perf(ctx: ScanContext) -> list[Finding]:
    """PF-07 渲染热点 + PF-08 Provider 未 memo 化。"""
    findings: list[Finding] = []
    for path in ctx.frontend_files:
        if _is_skipped(path):
            continue
        text = ctx.text(path)
        if not text:
            continue
        rel = rel_posix(path, ctx.root)
        findings.extend(_index_key(rel, text))
        findings.extend(_inline_props(rel, text))
        findings.extend(_provider_value(rel, text))
    return findings


def _index_key(rel: str, text: str) -> list[Finding]:
    """以数组下标作 key（重排/删除时整段重渲染）。"""
    lines = text.splitlines()
    for index, line in enumerate(lines, start=1):
        if config.RE_KEY_BY_INDEX.search(line):
            return [_mk(
                "PF-07", rel, index, "<jsx>", "index-key",
                "渲染热点：以数组下标作 React key，列表重排/删除会导致整段重渲染与状态错位",
                "改用稳定业务 id（如 `key={order.id}`）；无 id 时用内容哈希或自增唯一键",
                Severity.LOW, 0.5)]
    return []


def _inline_props(rel: str, text: str) -> list[Finding]:
    """`.map` 渲染中内联对象/函数字面量（每渲染新建引用，破坏 memo）。"""
    if not config.RE_MAP_CALL.search(text):
        return []
    lines = text.splitlines()
    hit = next((i for i, line in enumerate(lines, start=1)
                if config.RE_INLINE_PROP.search(line)), None)
    if hit is None:
        return []
    return [_mk(
        "PF-07", rel, hit, "<jsx>", "inline-prop",
        "渲染热点：列表渲染中使用内联对象/函数字面量（每次渲染新建引用，memo 失效）",
        "把对象/回调提到组件外用 `useMemo`/`useCallback` 稳定引用，或直接传原始值",
        Severity.LOW, 1.0)]


def _provider_value(rel: str, text: str) -> list[Finding]:
    """Context Provider 的 value 为对象字面量（每次渲染全树重渲染）。"""
    findings: list[Finding] = []
    for match in config.RE_PROVIDER_INLINE_VALUE.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        findings.append(_mk(
            "PF-08", rel, line, "<context>", f"provider@{line}",
            "渲染热点：Context Provider 的 value 为对象字面量，父组件每次渲染都会触发全部消费者重渲染",
            "用 `useMemo` 包装 value（依赖项收敛到真正变化的字段），"
            "或按关注点拆分为多个 Context",
            Severity.MEDIUM, 1.0))
    return findings


def _mk(rule_id: str, rel: str, line: int, symbol: str, key: str, message: str,
        fix_hint: str, severity: Severity, effort: float) -> Finding:
    """构造 Finding。"""
    return Finding(
        rule_id=rule_id,
        ruleset=RuleSet.OE,
        severity=severity,
        file=rel,
        line=line,
        symbol=symbol,
        message=message,
        fix_hint=fix_hint,
        fingerprint=make_fingerprint(rule_id, rel, key),
        est_effort_h=effort,
    )
