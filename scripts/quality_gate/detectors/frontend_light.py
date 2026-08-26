"""OE-06/07 前端轻量检测器 — 未使用导出 / 超长组件（文本正则，零依赖）。

OE-06：构建全库 import/export 名字图，导出无任何消费者 → 未使用导出。
  豁免：re-export 不产生待判定项（归属在被 re-export 的源文件）；
  动态 import / ``import * as`` 视为整文件消费（保守方向）。
OE-07：tsx 文件超长 / useState 过多。

staged 模式：import 图仍全库构建（新增导出的消费者判定需要全景），
仅判定对象收敛为 staged 前端文件。
"""

from __future__ import annotations

import re

from .. import config
from ..ast_utils import make_fingerprint, rel_posix
from ..context import ScanContext
from ..models import Finding, RuleSet, Severity

# ── TS import/export 正则 ─────────────────────────────────────────

_RE_IMPORT = re.compile(
    r"^\s*import\s+(?:type\s+)?([\w*\s{},]+?)\s+from\s+['\"]([^'\"]+)['\"]")
_RE_SIDE_EFFECT_IMPORT = re.compile(r"^\s*import\s+['\"]([^'\"]+)['\"]")
_RE_DYNAMIC_IMPORT = re.compile(r"import\(\s*['\"]([^'\"]+)['\"]\s*\)")
_RE_EXPORT_DECL = re.compile(
    r"^\s*export\s+(?:default\s+)?(?:async\s+)?"
    r"(?:const|let|var|function\s*\*?|class|type|interface|enum)\s+(\w+)")
_RE_EXPORT_DEFAULT_EXPR = re.compile(r"^\s*export\s+default\s+[^A-Za-z]")
_RE_EXPORT_LIST = re.compile(
    r"^\s*export\s*\{([^}]*)\}\s*(?:from\s+['\"]([^'\"]+)['\"])?")
_RE_EXPORT_STAR = re.compile(r"^\s*export\s*\*\s*from\s+['\"]([^'\"]+)['\"]")
_RE_USE_STATE = re.compile(r"\buseState\s*[<(]")

# 相对导入解析的扩展名补全顺序
_EXT_PROBES = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")


def detect(ctx: ScanContext) -> list[Finding]:
    """OE-06（未使用导出）+ OE-07（超长组件 / useState 过多）。"""
    all_files = ctx.all_frontend_files
    exports, imports = _build_name_graph(ctx, all_files)
    findings: list[Finding] = []
    for path in ctx.frontend_files:
        rel = rel_posix(path, ctx.root)
        if _is_exempt(rel):
            continue
        text = ctx.text(path)
        if text is None:
            continue
        findings.extend(_detect_unused_exports(rel, path, exports, imports, all_files))
        findings.extend(_detect_component_bloat(rel, text))
    return findings


# ── OE-06：未使用导出 ─────────────────────────────────────────────

def _build_name_graph(ctx: ScanContext, all_files: list) -> tuple[dict, set]:
    """全库名字图：exports[文件] = {导出名}；imports = {(文件, 名字)}。

    re-export（``export {x} from './y'``）将 y 的 x 记为已消费，
    且不为当前文件产生待判定导出（避免 barrel 误报）。
    路径统一 posix 风格（Windows 反斜杠兼容）。
    """
    exports: dict[str, set[str]] = {}
    imports: set[tuple[str, str]] = set()
    file_set = {p.as_posix() for p in all_files}

    for path in all_files:
        text = ctx.text(path)
        if text is None:
            continue
        src = path.as_posix()
        for line in text.splitlines():
            _scan_line(ctx, src, line, file_set, exports, imports)
    return exports, imports


def _scan_line(ctx: ScanContext, src: str, line: str, file_set: set,
               exports: dict, imports: set) -> None:
    """解析单行 import/export，更新名字图。"""
    # import ... from 'path'
    m = _RE_IMPORT.match(line)
    if m:
        target = _resolve_path(ctx, m.group(2), src, file_set)
        if target:
            for name in _parse_import_names(m.group(1)):
                imports.add((target, name))
        return
    # 副作用 / 动态 import：整文件消费
    m = _RE_SIDE_EFFECT_IMPORT.match(line) or _RE_DYNAMIC_IMPORT.search(line)
    if m:
        target = _resolve_path(ctx, m.group(1), src, file_set)
        if target:
            imports.add((target, "*"))
        return
    # export 声明
    m = _RE_EXPORT_DECL.match(line)
    if m:
        exports.setdefault(src, set()).add(
            m.group(1) if not _is_default_export(line) else "default")
        return
    if _RE_EXPORT_DEFAULT_EXPR.match(line):
        exports.setdefault(src, set()).add("default")
        return
    # export { a, b as c } [from './x']
    m = _RE_EXPORT_LIST.match(line)
    if m:
        names, source = m.group(1), m.group(2)
        if source:
            target = _resolve_path(ctx, source, src, file_set)
            if target:
                for name in _parse_import_names(names):
                    imports.add((target, name))   # re-export = 消费源文件
        else:
            exports.setdefault(src, set()).update(_parse_import_names(names))
        return
    m = _RE_EXPORT_STAR.match(line)
    if m:
        target = _resolve_path(ctx, m.group(1), src, file_set)
        if target:
            imports.add((target, "*"))           # star re-export = 整文件消费


def _is_default_export(line: str) -> bool:
    """export 声明是否为 default 导出。"""
    return bool(re.match(r"^\s*export\s+default\b", line))


def _parse_import_names(clause: str) -> list[str]:
    """解析 import 子句中的名字（``a, b as c, {d}`` → [a, c, d]；``* as n`` → [*]）。"""
    clause = clause.strip().strip("{}")
    if "*" in clause:
        return ["*"]
    names: list[str] = []
    for part in clause.split(","):
        part = part.strip()
        if not part:
            continue
        # ``b as c`` 取绑定名 c；``type a`` 取 a
        tokens = part.replace("type ", "").split()
        names.append(tokens[-1] if tokens else part)
    return names


def _resolve_path(ctx: ScanContext, spec: str, importer: str, file_set: set) -> str | None:
    """解析 import 说明符到文件（相对路径 + 别名映射 + 扩展名补全）。"""
    if spec.startswith("."):
        base = _normalize(_dir_of(importer) + "/" + spec)
    elif spec.startswith("@"):
        prefix = spec.split("/")[0]
        mapped = config.FRONTEND_ALIASES.get(prefix)
        if mapped is None:
            return None
        # 别名挂载点为 frontend/src，mapped 为相对 src 的子路径（可能为空）
        rest = spec[len(prefix):].lstrip("/")
        rel_path = f"{mapped}/{rest}" if mapped and rest else (mapped or rest)
        base = _normalize(str(ctx.root / config.FRONTEND_SCAN_ROOT / rel_path))
    else:
        return None                          # npm 包不参与
    for ext in _EXT_PROBES:
        probe = base + ext if ext else base
        if probe in file_set:
            return probe
    return None


def _dir_of(path: str) -> str:
    """文件路径的目录部分（posix）。"""
    return path.rsplit("/", 1)[0] if "/" in path else "."


def _normalize(path) -> str:
    """路径归一化（消解 ./ ../ 与 Windows 分隔符）。"""
    parts = str(path).replace("\\", "/").split("/")
    out: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if out:
                out.pop()
            continue
        out.append(part)
    return "/".join(out)


def _detect_unused_exports(rel: str, path, exports: dict, imports: set,
                           all_files: list) -> list[Finding]:
    """判定单文件的未使用导出。"""
    src = path.as_posix()
    exported = exports.get(src, set())
    consumed_starmask = (src, "*") in imports
    if consumed_starmask:
        return []
    unused = sorted(
        name for name in exported
        if name != "default" and (src, name) not in imports
    )
    if not unused:
        return []
    return [
        Finding(
            rule_id="OE-06",
            ruleset=RuleSet.OE,
            severity=Severity.LOW,
            file=rel,
            line=1,
            symbol=name,
            message=f"未使用导出: {name}（全库无消费者引用）",
            fix_hint="删除该导出及其实现；若为公共 API 预留请 suppressed 注明",
            fingerprint=make_fingerprint("OE-06", rel, name),
            est_effort_h=0.25,
        )
        for name in unused
    ]


# ── OE-07：超长组件 / useState 过多 ───────────────────────────────

def _detect_component_bloat(rel: str, text: str) -> list[Finding]:
    """文件级组件膨胀检测。"""
    findings: list[Finding] = []
    line_count = len(text.splitlines())
    if line_count > config.MAX_COMPONENT_LINES:
        findings.append(Finding(
            rule_id="OE-07",
            ruleset=RuleSet.OE,
            severity=Severity.MEDIUM,
            file=rel,
            line=1,
            symbol="<file>",
            message=f"超长组件文件: {line_count} 行 > {config.MAX_COMPONENT_LINES} 行",
            fix_hint="按 UI 区块拆分子组件；数据逻辑提取为自定义 hook",
            fingerprint=make_fingerprint("OE-07", rel, "length"),
            est_effort_h=1.0,
        ))
    state_count = len(_RE_USE_STATE.findall(text))
    if state_count > config.MAX_USE_STATE:
        findings.append(Finding(
            rule_id="OE-07",
            ruleset=RuleSet.OE,
            severity=Severity.MEDIUM,
            file=rel,
            line=1,
            symbol="<file>",
            message=f"useState 过多: {state_count} 个 > {config.MAX_USE_STATE} 个",
            fix_hint="将关联状态合并为单一对象，或提取 useReducer / 自定义 hook",
            fingerprint=make_fingerprint("OE-07", rel, "use-state"),
            est_effort_h=1.0,
        ))
    return findings


def _is_exempt(rel: str) -> bool:
    """前端检测豁免：入口 / 注册表 / 类型声明。"""
    frontend_rel = rel[len("frontend/"):] if rel.startswith("frontend/") else rel
    return frontend_rel in config.FRONTEND_EXEMPT_FILES or frontend_rel.endswith(".d.ts")
