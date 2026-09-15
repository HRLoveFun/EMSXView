"""CL-12 过时类方法 — 类方法级零引用候选（补齐 CL-02 的能力边界）。

CL-02 只判模块级符号，类方法死代码过去需依赖外部工具（vulture）；本检测器用纯标准库补齐。

**两条关键设计**（均由实测漏报反推，见 skill 复盘日志）：

1. **词边界匹配**：以 ``(?<![\\w.])name(?![\\w])`` 判定「出现」，而非子串 ``in``。
   ``_`` 属于 ``\\w``，故 ``get_distinct_dates`` 不会被 ``get_distinct_dates_in_range``
   遮蔽 —— 子串匹配会把真死方法判为存活（假阴性）。
2. **同名实体区分**：某文件若自带同名**模块级**符号（def / class / 赋值 / import），
   该文件内的**裸标识符**出现归属其自有符号，不计为对本方法的引用；只有属性访问
   形态（``obj.name`` / ``self.name``）才算潜在引用。用于排除
   「同名模块级函数被裸调用」造成的假阴性（实测 ``_fill_bdib_conn`` 即此类）。

**保守取向**（漏报可接受、误删不可接受）：
- 未被上述规则归类的任何出现（含注释、字符串、``getattr(obj, "name")``）一律计为引用；
- 类体内含动态名字访问（getattr / vars / locals / …）或代理 dunder 时整类放弃判定；
- 框架/多态基类（Protocol / ABC / BaseModel / Enum / TestCase / NodeVisitor…）整类豁免；
- dunder 方法、框架装饰器、桩代码目录、测试目录豁免。
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from scripts.quality_gate.ast_utils import make_fingerprint, rel_posix
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding, RuleSet, Severity

from .. import config
from ..names import decorator_tokens, is_framework_decorated

_TOKEN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")
_CLASS_RE = re.compile(r"^\s*class\s+([A-Za-z_]\w*)")


@dataclass(frozen=True)
class _Candidate:
    """单个候选方法（定义处信息）。"""

    path: Path
    rel: str
    class_name: str
    name: str
    line: int
    loc: int


def detect(ctx: ScanContext) -> list[Finding]:
    """扫描类方法并输出全库零引用候选项。"""
    candidates = _collect(ctx)
    if not candidates:
        return []
    index = _OccurrenceIndex(ctx, {cand.name for cand in candidates})
    findings: list[Finding] = []
    for cand in candidates:
        refs, excluded = index.evidence(cand)
        if refs:
            continue
        findings.append(_finding(cand, excluded))
    return findings


# ── 候选收集（含豁免） ────────────────────────────────────────────

def _collect(ctx: ScanContext) -> list[_Candidate]:
    """收集未被豁免的类方法候选。"""
    out: list[_Candidate] = []
    for path in ctx.python_files:
        if _path_exempt(path):
            continue
        tree = ctx.tree(path)
        if tree is None or _has_module_proxy(tree):
            continue
        rel = rel_posix(path, ctx.root)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or _class_exempt(node):
                continue
            for sub in node.body:
                if not isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if _method_exempt(sub):
                    continue
                end = sub.end_lineno or sub.lineno
                out.append(_Candidate(path, rel, node.name, sub.name, sub.lineno,
                                      end - sub.lineno + 1))
    return out


def _path_exempt(path: Path) -> bool:
    """测试目录与桩/替身代码目录豁免。"""
    parts = [part.lower() for part in path.parts]
    if any(part in config.EXEMPT_DIR_PARTS for part in path.parts):
        return True
    return any(hint in part for part in parts
               for hint in config.CLASS_METHOD_STUB_PATH_PARTS)


def _has_module_proxy(tree: ast.Module) -> bool:
    """模块级 ``__getattr__``（PEP 562）说明属性可被动态兜底 → 全文件放弃判定。"""
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name in config.CLASS_METHOD_DYNAMIC_DUNDERS for node in tree.body)


def _class_exempt(node: ast.ClassDef) -> bool:
    """框架基类或类体内动态名字访问 → 整类豁免。"""
    bases = {b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", "")
             for b in node.bases}
    if bases & config.CLASS_METHOD_EXEMPT_BASES:
        return True
    return any(isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
               and child.name in config.CLASS_METHOD_DYNAMIC_DUNDERS for child in node.body) \
        or _has_dynamic_access(node)


def _has_dynamic_access(node: ast.AST) -> bool:
    """是否存在动态名字访问调用。"""
    return any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
               and child.func.id in config.CLASS_METHOD_DYNAMIC_CALLS
               for child in ast.walk(node))


def _method_exempt(func: ast.stmt) -> bool:
    """dunder / 框架装饰器 / 占位声明 / 契约豁免名单。"""
    name = getattr(func, "name", "")
    if name.startswith("__") and name.endswith("__"):
        return True
    if name in config.DEAD_METHOD_EXEMPT_NAMES:
        return True
    tokens = decorator_tokens(func)
    if is_framework_decorated(tokens) or tokens & config.EMPTY_STUB_EXEMPT_DECORATORS:
        return True
    docstring = ast.get_docstring(func) or ""
    return any(hint in docstring for hint in config.EMPTY_STUB_PLACEHOLDER_HINTS)


# ── 出现索引与同名实体区分 ────────────────────────────────────────

class _OccurrenceIndex:
    """候选方法名在全库语料中的出现索引（含同名实体归属判定）。"""

    def __init__(self, ctx: ScanContext, names: set[str]) -> None:
        self._names = names
        self._occurrences: dict[str, list[tuple[Path, int, str]]] = defaultdict(list)
        self._own_symbols: dict[Path, frozenset[str]] = {}
        for path in [*ctx.all_python_files, *ctx.all_frontend_files]:
            if any(part in config.CORPUS_EXCLUDE_PARTS for part in path.parts):
                continue
            text = ctx.text(path)
            if text is None:
                continue
            self._own_symbols[path] = _module_level_symbols(ctx.tree(path))
            self._index_lines(path, text)

    def _index_lines(self, path: Path, text: str) -> None:
        """按词元登记候选名的出现位置（词边界等价，且只登记候选名）。"""
        for lineno, line in enumerate(text.splitlines(), 1):
            for token in set(_TOKEN.findall(line)):
                if token in self._names:
                    self._occurrences[token].append((path, lineno, line))

    def evidence(self, cand: _Candidate) -> tuple[int, int]:
        """返回 ``(引用数, 被判为同名实体的出现数)``。"""
        refs = 0
        excluded = 0
        for path, lineno, line in self._occurrences.get(cand.name, []):
            if path == cand.path and lineno == cand.line:
                continue
            if self._is_reference(cand, path, line):
                refs += 1
            else:
                excluded += 1
        return refs, excluded

    def _is_reference(self, cand: _Candidate, path: Path, line: str) -> bool:
        """该次出现是否构成对候选方法的引用。"""
        if _DEF_RE.match(line) or _CLASS_RE.match(line):
            return False                                   # 同名符号的定义处
        if line.lstrip().startswith(("import ", "from ")):
            return False                                   # 同名模块级符号的导入
        if path != cand.path and cand.name in self._own_symbols.get(path, frozenset()):
            return _is_attribute_access(line, cand.name)    # 裸标识符归属该文件自有符号
        return True


def _module_level_symbols(tree: ast.Module | None) -> frozenset[str]:
    """模块级定义的符号名（def / class / 赋值 / import）。"""
    if tree is None:
        return frozenset()
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            names |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            names |= {a.asname or a.name for a in node.names}
    return frozenset(names)


@lru_cache(maxsize=512)
def _attribute_pattern(name: str) -> re.Pattern[str]:
    """``.name`` 属性访问正则（按名缓存，避免逐次编译）。"""
    return re.compile(r"\.\s*" + re.escape(name) + r"(?![\w])")


def _is_attribute_access(line: str, name: str) -> bool:
    """行内是否存在 ``.name`` 形态的属性访问。"""
    return _attribute_pattern(name).search(line) is not None


def _finding(cand: _Candidate, excluded: int) -> Finding:
    """构造 CL-12 Finding（长方法判 medium）。"""
    severity = Severity.MEDIUM if cand.loc >= config.DEAD_METHOD_MEDIUM_LOC else Severity.LOW
    extra = f"，已排除同名实体出现 {excluded} 处" if excluded else ""
    return Finding(
        rule_id="CL-12",
        ruleset=RuleSet.OE,
        severity=severity,
        file=cand.rel,
        line=cand.line,
        symbol=f"{cand.class_name}.{cand.name}",
        message=f"过时类方法：`{cand.class_name}.{cand.name}` 全库零引用"
                f"（{cand.loc} 行{extra}）",
        fix_hint="确认非反射/回调/框架钩子后删除；若为协议实现或外部调用入口，"
                 "`--suppress <fingerprint>` 豁免并注明理由",
        fingerprint=make_fingerprint("CL-12", cand.rel, f"{cand.class_name}.{cand.name}"),
        est_effort_h=0.5 if severity is Severity.MEDIUM else 0.25,
    )
