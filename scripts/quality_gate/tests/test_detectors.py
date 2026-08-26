"""质量门禁检测器单测 — 人造过度工程 fixture 验证各检测器的判定正确性。

运行：``python -m pytest scripts/quality_gate/tests/ -v``
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from scripts.quality_gate import config
from scripts.quality_gate.ast_utils import (
    cyclomatic_complexity,
    func_line_count,
    make_fingerprint,
    nesting_depth,
    param_count,
)
from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.detectors import complexity, dead_modules, duplication
from scripts.quality_gate.detectors import frontend_light, needless_patterns, over_abstraction
from scripts.quality_gate.models import Finding, RuleSet, Severity


# ── AST 工具单测 ──────────────────────────────────────────────────

class TestAstUtils:
    """ast_utils 公共工具。"""

    def _func(self, code: str) -> ast.FunctionDef:
        tree = ast.parse(textwrap.dedent(code))
        return next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))

    def test_cyclomatic_complexity_flat(self):
        """无分支函数 CC=1。"""
        func = self._func("def f():\n    return 1\n")
        assert cyclomatic_complexity(func) == 1

    def test_cyclomatic_complexity_branches(self):
        """if/for/while/and 各 +1。"""
        func = self._func("""
            def f(a):
                if a:
                    return 1
                for i in range(10):
                    pass
                while a:
                    pass
                return a and f(a)
        """)
        # 基础1 + if(1) + for(1) + while(1) + and(1) = 5
        assert cyclomatic_complexity(func) == 5

    def test_nesting_depth_flat(self):
        """无嵌套 depth=0。"""
        func = self._func("def f():\n    return 1\n")
        assert nesting_depth(func.body) == 0

    def test_nesting_depth_nested(self):
        """3 层嵌套 depth=3。"""
        func = self._func("""
            def f(a):
                if a:
                    if a:
                        if a:
                            return 1
                return 0
        """)
        assert nesting_depth(func.body) == 3

    def test_param_count_self_excluded(self):
        """self/cls 不计入参数个数。"""
        func = self._func("def f(self, a, b):\n    pass\n")
        assert param_count(func) == 2

    def test_func_line_count(self):
        """函数行数。"""
        func = self._func("def f():\n    return 1\n")
        assert func_line_count(func) == 2

    def test_make_fingerprint_deterministic(self):
        """相同输入产出相同指纹。"""
        assert make_fingerprint("a", "b") == make_fingerprint("a", "b")
        assert make_fingerprint("a", "b") != make_fingerprint("a", "c")


# ── OE-05 复杂度检测器 ─────────────────────────────────────────────

class TestComplexityDetector:
    """OE-05 圈复杂度/嵌套/参数/长度检测。"""

    def test_overly_complex_function_detected(self, tmp_path, monkeypatch):
        """超长嵌套+参数超标的函数应被检出。"""
        src = tmp_path / "test_module.py"
        src.write_text(textwrap.dedent("""
            def overly_complex(a, b, c, d, e, f, g, h, i, j):
                if a:
                    if b:
                        if c:
                            if d:
                                if e:
                                    return 1
                return 0
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = complexity.detect(ctx)
        rules = {f.message for f in findings}
        assert any("嵌套深度" in m for m in rules)
        assert any("参数个数" in m for f in findings for m in [f.message])

    def test_simple_function_not_flagged(self, tmp_path, monkeypatch):
        """简单函数不应被检出。"""
        src = tmp_path / "simple.py"
        src.write_text("def f(a, b):\n    return a + b\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        assert complexity.detect(ctx) == []


# ── OE-02 过度抽象检测器 ──────────────────────────────────────────

class TestOverAbstractionDetector:
    """OE-02 单实现 ABC / 1:1 传递函数。"""

    def test_single_impl_abc_detected(self, tmp_path, monkeypatch):
        """单实现 ABC（实现 <50 行）应被检出。"""
        src = tmp_path / "abstract.py"
        src.write_text(textwrap.dedent("""
            from abc import ABC, abstractmethod

            class Animal(ABC):
                @abstractmethod
                def speak(self) -> str: ...

            class Dog(Animal):
                def speak(self) -> str:
                    return "woof"
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = over_abstraction.detect(ctx)
        assert any(f.symbol == "Animal" for f in findings)

    def test_forwarding_wrapper_detected(self, tmp_path, monkeypatch):
        """1:1 传递函数（单调用方）应被检出。"""
        src = tmp_path / "wrapper.py"
        src.write_text(textwrap.dedent("""
            def _impl(x, y):
                return x + y

            def wrapper(x, y):
                return _impl(x, y)

            result = wrapper(1, 2)
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = over_abstraction.detect(ctx)
        assert any(f.symbol == "wrapper" for f in findings)

    def test_decorated_function_not_flagged(self, tmp_path, monkeypatch):
        """带装饰器的函数不判为传递包装（框架挂点）。"""
        src = tmp_path / "router.py"
        src.write_text(textwrap.dedent("""
            def _impl(req):
                return req

            def decorator(fn):
                return fn

            @decorator
            def endpoint(req):
                return _impl(req)
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = over_abstraction.detect(ctx)
        assert not any(f.symbol == "endpoint" for f in findings)


# ── OE-03 设计模式检测器 ──────────────────────────────────────────

class TestNeedlessPatternsDetector:
    """OE-03 过深继承链 / 单产品工厂。"""

    def test_deep_inheritance_detected(self, tmp_path, monkeypatch):
        """5 层继承链（4 边）应被检出（阈值 3 边）。"""
        src = tmp_path / "inheritance.py"
        src.write_text(textwrap.dedent("""
            class A: pass
            class B(A): pass
            class C(B): pass
            class D(C): pass
            class E(D): pass
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = needless_patterns.detect(ctx)
        assert any("继承链过深" in f.message for f in findings)

    def test_shallow_inheritance_not_flagged(self, tmp_path, monkeypatch):
        """2 层继承不应被检出。"""
        src = tmp_path / "shallow.py"
        src.write_text(textwrap.dedent("""
            class A: pass
            class B(A): pass
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        assert needless_patterns.detect(ctx) == []


# ── OE-04 重复检测器 ──────────────────────────────────────────────

class TestDuplicationDetector:
    """OE-04 重复代码块。"""

    def test_duplicate_functions_detected(self, tmp_path, monkeypatch):
        """两个归一化后相同的函数（≥30 行）应被检出。"""
        body = textwrap.dedent("""\
            result = []
            for item in data:
                if item > threshold:
                    result.append(item * 2)
                    result.append(item * 3)
                    result.append(item * 4)
                    result.append(item * 5)
                    result.append(item * 6)
                    result.append(item * 7)
                    result.append(item * 8)
                    result.append(item * 9)
                    result.append(item * 10)
                    result.append(item * 11)
                    result.append(item * 12)
                    result.append(item * 13)
                    result.append(item * 14)
                    result.append(item * 15)
                else:
                    result.append(item * 0.5)
                    result.append(item * 0.6)
                    result.append(item * 0.7)
                    result.append(item * 0.8)
                    result.append(item * 0.9)
                    result.append(item * 1.0)
                    result.append(item * 1.1)
                    result.append(item * 1.2)
                    result.append(item * 1.3)
                    result.append(item * 1.4)
                    result.append(item * 1.5)
                    result.append(item * 1.6)
                    result.append(item * 1.7)
                    result.append(item * 1.8)
            return result
        """)
        indented = textwrap.indent(body, "    ")
        src = tmp_path / "dup.py"
        src.write_text(
            f"def process_alpha(data, threshold):\n{indented}\n\n"
            f"def process_beta(values, limit):\n{indented}\n",
            encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        findings = duplication.detect(ctx)
        assert len(findings) >= 2  # 两个函数各一个 finding

    def test_unique_functions_not_flagged(self, tmp_path, monkeypatch):
        """不同结构的函数不应被检出。"""
        src = tmp_path / "unique.py"
        src.write_text(textwrap.dedent("""
            def add(a, b):
                return a + b

            def multiply(a, b):
                return a * b
        """), encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[src], frontend_files=[],
            all_python_files=[src], all_frontend_files=[],
        )
        assert duplication.detect(ctx) == []


# ── OE-01 死模块检测器 ───────────────────────────────────────────

class TestDeadModulesDetector:
    """OE-01 冗余模块（import 图可达性）。"""

    def test_unreachable_module_detected(self, tmp_path, monkeypatch):
        """无任何引用的模块应被检出。"""
        entry = tmp_path / "main.py"
        entry.write_text("print('entry')\n", encoding="utf-8")
        orphan = tmp_path / "orphan.py"
        orphan.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[orphan], frontend_files=[],
            all_python_files=[entry, orphan], all_frontend_files=[],
        )
        findings = dead_modules.detect(ctx)
        assert any("orphan" in f.file for f in findings)

    def test_reachable_module_not_flagged(self, tmp_path, monkeypatch):
        """被入口引用的模块不应被检出。"""
        entry = tmp_path / "main.py"
        entry.write_text("import lib\n", encoding="utf-8")
        lib = tmp_path / "lib.py"
        lib.write_text("x = 1\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[lib], frontend_files=[],
            all_python_files=[entry, lib], all_frontend_files=[],
        )
        assert dead_modules.detect(ctx) == []


# ── OE-06/07 前端轻量检测器 ───────────────────────────────────────

class TestFrontendLightDetector:
    """OE-06 未使用导出 / OE-07 超长组件。"""

    def test_unused_export_detected(self, tmp_path, monkeypatch):
        """无消费者的导出应被检出。"""
        frontend = tmp_path / "frontend" / "src"
        frontend.mkdir(parents=True)
        (frontend / "unused.ts").write_text(
            "export function unusedFn(): void {}\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[], frontend_files=[frontend / "unused.ts"],
            all_python_files=[], all_frontend_files=[frontend / "unused.ts"],
        )
        findings = frontend_light.detect(ctx)
        assert any(f.symbol == "unusedFn" for f in findings)

    def test_used_export_not_flagged(self, tmp_path, monkeypatch):
        """被消费的导出不应被检出。"""
        frontend = tmp_path / "frontend" / "src"
        frontend.mkdir(parents=True)
        (frontend / "lib.ts").write_text(
            "export function usedFn(): void {}\n", encoding="utf-8")
        (frontend / "app.ts").write_text(
            "import { usedFn } from './lib';\n", encoding="utf-8")
        monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
        ctx = ScanContext(
            root=tmp_path, mode="full",
            python_files=[], frontend_files=[frontend / "lib.ts"],
            all_python_files=[],
            all_frontend_files=[frontend / "lib.ts", frontend / "app.ts"],
        )
        findings = frontend_light.detect(ctx)
        assert not any(f.symbol == "usedFn" for f in findings)
