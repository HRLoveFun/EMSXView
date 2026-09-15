"""清理门禁检测器单测 — 人造 fixture 验证「命中」与「不误报」两侧。

运行：``python -m pytest scripts/cleanup/tests/ -v``
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.cleanup.detectors import (
    dead_files,
    dead_logic,
    dead_methods,
    dead_symbols,
    frontend,
    perf,
)
from scripts.quality_gate.context import ScanContext


def _ctx(tmp_path: Path, files: dict[str, str]) -> ScanContext:
    """在临时目录搭建迷你仓库并返回扫描上下文。"""
    for rel, content in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    python_files = sorted(tmp_path.rglob("*.py"))
    frontend_files = sorted(p for p in tmp_path.rglob("*") if p.suffix in (".ts", ".tsx"))
    return ScanContext(
        root=tmp_path,
        mode="full",
        python_files=python_files,
        frontend_files=frontend_files,
        all_python_files=python_files,
        all_frontend_files=frontend_files,
    )


def _rules(findings: list) -> dict[str, list]:
    """按规则号分组。"""
    out: dict[str, list] = {}
    for finding in findings:
        out.setdefault(finding.rule_id, []).append(finding)
    return out


def _rel(finding: object) -> str:
    """finding 的文件路径（posix，便于跨平台断言）。"""
    return getattr(finding, "file").replace("\\", "/")


# ── CL-03 不可达代码 ──────────────────────────────────────────────

class TestUnreachable:
    """CL-03。"""

    def test_reports_statement_after_return(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f():
                return 1
                x = 2
        """})
        rules = _rules(dead_logic.detect(ctx))
        assert [f.line for f in rules["CL-03"]] == [3]

    def test_ignores_return_at_tail(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f(flag):
                if flag:
                    return 1
                return 2
        """})
        assert "CL-03" not in _rules(dead_logic.detect(ctx))


# ── CL-04 恒定条件 / 等价分支 ─────────────────────────────────────

class TestConstantCondition:
    """CL-04。"""

    def test_reports_constant_if(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f():
                if False:
                    return 1
                return 2
        """})
        rules = _rules(dead_logic.detect(ctx))
        assert rules["CL-04"][0].line == 2

    def test_reports_identical_branches(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f(flag):
                if flag:
                    return 1
                else:
                    return 1
        """})
        assert "const-if" not in "".join(f.symbol for f in dead_logic.detect(ctx))
        assert "CL-04" in _rules(dead_logic.detect(ctx))

    def test_ignores_type_checking_guard(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            from typing import TYPE_CHECKING

            if TYPE_CHECKING:
                import os
        """})
        assert "CL-04" not in _rules(dead_logic.detect(ctx))


# ── CL-05 空实现存根 ──────────────────────────────────────────────

class TestEmptyStub:
    """CL-05。"""

    def test_reports_pass_only_function(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def todo_handler():
                pass
        """})
        rules = _rules(dead_logic.detect(ctx))
        assert [f.symbol for f in rules["CL-05"]] == ["todo_handler"]

    def test_ignores_protocol_method(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            from typing import Protocol

            class Runner(Protocol):
                def run(self) -> None:
                    ...
        """})
        assert "CL-05" not in _rules(dead_logic.detect(ctx))

    def test_ignores_route_handler_stub(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            from fastapi import APIRouter

            router = APIRouter()

            @router.post("/noop")
            async def noop_endpoint():
                pass
        """})
        assert "CL-05" not in _rules(dead_logic.detect(ctx))


# ── CL-06 未使用局部变量 ──────────────────────────────────────────

class TestUnusedLocal:
    """CL-06。"""

    def test_reports_unused_assignment(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f():
                total = 1 + 1
                return 2
        """})
        rules = _rules(dead_logic.detect(ctx))
        assert "total" in rules["CL-06"][0].message

    def test_ignores_loop_target_and_dynamic_access(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def f(rows):
                for item in rows:
                    pass

            def g(rows):
                value = 1
                return locals()
        """})
        assert "CL-06" not in _rules(dead_logic.detect(ctx))


# ── CL-07 / CL-08 / CL-09 文件级与注释级 ──────────────────────────

class TestFileLevelCleanup:
    """CL-07 / CL-08 / CL-09。"""

    def test_reports_temp_leftover(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/_tmp_probe.py": "VALUE = 1\n"})
        rules = _rules(dead_files.detect(ctx))
        assert rules["CL-07"][0].symbol == "_tmp_probe"

    def test_ignores_normal_module_name(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/debug_utils.py": "def debug_port():\n    return 1\n"})
        assert "CL-07" not in _rules(dead_files.detect(ctx))

    def test_reports_empty_module(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/placeholder.py": '"""占位。"""\n'})
        rules = _rules(dead_files.detect(ctx))
        assert rules["CL-08"][0].symbol == "placeholder"

    def test_reports_commented_code_block(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            # def old_flow(data):
            #     result = transform(data)
            #     return result
            #     log(result)
            VALUE = 1
        """})
        rules = _rules(dead_logic.detect(ctx))
        assert rules["CL-09"][0].line == 1


# ── CL-02 过时符号 ────────────────────────────────────────────────

class TestDeadSymbol:
    """CL-02。"""

    def test_reports_orphan_function(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/m.py": """
            def orphan_helper():
                return 1
        """})
        rules = _rules(dead_symbols.detect(ctx))
        assert [f.symbol for f in rules["CL-02"]] == ["orphan_helper"]

    def test_ignores_symbol_used_by_other_file(self, tmp_path):
        ctx = _ctx(tmp_path, {
            "pkg/m.py": "def helper():\n    return 1\n",
            "pkg/use.py": "from pkg.m import helper\n\nVALUE = helper()\n",
        })
        symbols = {f.symbol for f in dead_symbols.detect(ctx)}
        assert "helper" not in symbols          # 跨文件被引用
        assert "VALUE" in symbols               # 自身零引用，应被报出

    def test_ignores_decorated_and_subclassed(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/m.py": """
            from functools import lru_cache

            @lru_cache(maxsize=8)
            def cached_helper():
                return 1

            class Derived(dict):
                pass
        """})
        assert "CL-02" not in _rules(dead_symbols.detect(ctx))

    def test_ignores_route_handler(self, tmp_path):
        ctx = _ctx(tmp_path, {"pkg/routes.py": """
            from fastapi import APIRouter

            router = APIRouter()

            @router.get("/orders")
            async def list_orders():
                return []
        """})
        assert "CL-02" not in _rules(dead_symbols.detect(ctx))


# ── PF-01 ~ PF-06 后端性能 ───────────────────────────────────────

class TestBackendPerf:
    """PF-01 ~ PF-06。"""

    def test_reports_loop_io(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def load(conn, ids):
                for order_id in ids:
                    conn.execute("select 1 where id = ?", (order_id,))
        """})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-01"][0].line == 2

    def test_ignores_dict_get_in_loop(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def pick(rows, mapping):
                for row in rows:
                    print(mapping.get(row))
        """})
        assert "PF-01" not in _rules(perf.detect(ctx))

    def test_ignores_io_in_for_header(self, tmp_path):
        """``for r in cursor.fetchall()`` 的迭代表达式只求值一次，不是 N+1。"""
        ctx = _ctx(tmp_path, {"m.py": """
            def dump(conn):
                for row in conn.execute("select 1").fetchall():
                    print(row)
        """})
        assert "PF-01" not in _rules(perf.detect(ctx))

    def test_reports_io_in_while_condition(self, tmp_path):
        """``while`` 的条件每轮求值，仍应判为循环内 IO。"""
        ctx = _ctx(tmp_path, {"m.py": """
            def poll(conn):
                while conn.execute("select 1").fetchone():
                    print("tick")
        """})
        assert "PF-01" in _rules(perf.detect(ctx))

    def test_reports_nested_loop(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def pair(left, right):
                for a in left:
                    for b in right:
                        print(a, b)
        """})
        rules = _rules(perf.detect(ctx))
        assert all("嵌套" in f.message for f in rules["PF-02"])
        assert rules["PF-02"][0].severity.value == "low"     # 2 层判 low

    def test_three_level_loop_is_medium(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def cube(a, b, c):
                for i in a:
                    for j in b:
                        for k in c:
                            print(i, j, k)
        """})
        rules = _rules(perf.detect(ctx))
        assert any(f.severity.value == "medium" for f in rules["PF-02"])

    def test_reports_select_star_without_limit(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": 'QUERY = "SELECT * FROM fills"\n'})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-03"][0].line == 1

    def test_ignores_select_star_with_limit(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": 'QUERY = "SELECT * FROM fills LIMIT 100"\n'})
        assert "PF-03" not in _rules(perf.detect(ctx))

    def test_ignores_select_star_in_docstring(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": '''
            """示例：SELECT * FROM read_parquet(\'x/*.parquet\')。"""

            VALUE = 1
        '''})
        assert "PF-03" not in _rules(perf.detect(ctx))

    def test_ignores_lazy_view_definition(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": '''
            DDL = """
                CREATE OR REPLACE VIEW bars AS
                SELECT * FROM read_parquet('x/*.parquet')
            """
        '''})
        assert "PF-03" not in _rules(perf.detect(ctx))

    def test_fstring_limited_query_is_not_medium(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": '''
            def load(where):
                return f"""SELECT * FROM fills
                    {where}
                    LIMIT ? OFFSET ?"""
        '''})
        rules = _rules(perf.detect(ctx))
        assert all(f.severity.value == "low" for f in rules.get("PF-03", []))

    def test_select_star_with_where_is_low(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": 'QUERY = "SELECT * FROM fills WHERE source_date = ?"\n'})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-03"][0].severity.value == "low"

    def test_registry_table_full_read_is_low(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": 'QUERY = "SELECT * FROM equ_ticker_registry"\n'})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-03"][0].severity.value == "low"

    def test_reports_non_sargable_where(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": (
            'QUERY = "SELECT * FROM raw_fills WHERE substr(order_as_of_date, 1, 10) = ?"\n'
        )})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-09"][0].symbol == "raw_fills"

    def test_ignores_sargable_range_condition(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": (
            'QUERY = "SELECT * FROM raw_fills WHERE order_as_of_date >= ?'
            ' AND order_as_of_date < ?"\n'
        )})
        assert "PF-09" not in _rules(perf.detect(ctx))

    def test_reports_unbounded_container(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            CACHE = {}

            def put(key, value):
                CACHE[key] = value
        """})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-04"][0].symbol == "CACHE"

    def test_ignores_container_with_eviction(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            CACHE = {}

            def put(key, value):
                if len(CACHE) > 100:
                    CACHE.pop(next(iter(CACHE)))
                CACHE[key] = value
        """})
        assert "PF-04" not in _rules(perf.detect(ctx))

    def test_ignores_registry_container(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            _impl_registry: dict[str, object] = {}

            def register(impl, key="default"):
                _impl_registry[key] = impl
        """})
        assert "PF-04" not in _rules(perf.detect(ctx))

    def test_ignores_constant_key_growth(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            STATE = {}

            def bootstrap(cls):
                STATE["default"] = cls
        """})
        assert "PF-04" not in _rules(perf.detect(ctx))

    def test_reports_string_concat_in_loop(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            def render(items):
                output = ""
                for item in items:
                    output += str(item)
                return output
        """})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-05"][0].line == 3

    def test_reports_hotspot_candidate(self, tmp_path):
        body = "\n".join(f"                value_{i} = 1" for i in range(30))
        ctx = _ctx(tmp_path, {"m.py": (
            "def heavy(rows):\n"
            "    for row in rows:\n"
            "        if row:\n"
            "            for cell in row:\n"
            "                pass\n"
            f"{body}\n"
        )})
        rules = _rules(perf.detect(ctx))
        assert rules["PF-06"][0].symbol == "heavy"

    def test_hotspot_only_in_full_mode(self, tmp_path):
        body = "\n".join(f"                value_{i} = 1" for i in range(30))
        ctx = _ctx(tmp_path, {"m.py": (
            "def heavy(rows):\n"
            "    for row in rows:\n"
            "        if row:\n"
            "            for cell in row:\n"
            "                pass\n"
            f"{body}\n"
        )})
        ctx.mode = "staged"                              # 全局排序在增量模式下无意义
        assert "PF-06" not in _rules(perf.detect(ctx))


# ── CL-10 / PF-07 / PF-08 前端 ───────────────────────────────────

class TestFrontend:
    """CL-10 / PF-07 / PF-08。"""

    def test_reports_unreachable_file(self, tmp_path):
        ctx = _ctx(tmp_path, {
            "frontend/src/main.tsx": "import App from './app/App'\n",
            "frontend/src/app/App.tsx": "export default 1\n",
            "frontend/src/app/Orphan.tsx": "export const Orphan = 1\n",
        })
        rules = _rules(frontend.detect_cleanup(ctx))
        assert [_rel(f) for f in rules["CL-10"]] == \
            ["frontend/src/app/Orphan.tsx"]

    def test_reports_index_key(self, tmp_path):
        ctx = _ctx(tmp_path, {"frontend/src/app/List.tsx": """
            export const List = ({ items }) => (
              <ul>{items.map((item, index) => <li key={index}>{item}</li>)}</ul>
            )
        """})
        rules = _rules(frontend.detect_perf(ctx))
        assert rules["PF-07"][0].rule_id == "PF-07"

    def test_reports_provider_inline_value(self, tmp_path):
        ctx = _ctx(tmp_path, {"frontend/src/app/Shell.tsx": """
            export const Shell = ({ children, value }) => (
              <ThemeContext.Provider value={{ value }}>
                {children}
              </ThemeContext.Provider>
            )
        """})
        rules = _rules(frontend.detect_perf(ctx))
        assert rules["PF-08"][0].line == 2


# ── 全检测器冒烟 ─────────────────────────────────────────────────

def test_all_detectors_run_without_exception(tmp_path):
    """注册表内全部检测器在混合 fixture 上不抛异常。"""
    ctx = _ctx(tmp_path, {
        "pkg/m.py": """
            CACHE = {}

            def orphan(conn, rows):
                output = ""
                for row in rows:
                    conn.execute("select 1")
                    output += "x"
                    if False:
                        return output
        """,
        "frontend/src/main.tsx": "import App from './app/App'\n",
        "frontend/src/app/App.tsx": "export default 1\n",
    })
    from scripts.cleanup.detectors import FULL_DETECTORS

    for detector in FULL_DETECTORS:
        assert isinstance(detector(ctx), list)


# ── CL-10 前端图路径解析（跨平台回归） ─────────────────────────────

class TestFrontendGraphPaths:
    """CL-10：POSIX 绝对根（Linux / CI）下的说明符解析（回归）。

    历史缺陷：路径归一化丢弃 POSIX 根 ``/`` ⇒ 解析结果与 ``Path.as_posix()``
    永不相等 ⇒ CI 上 166 个前端文件被误报为不可达。Windows 本地因盘符占首位而不复现。
    """

    def test_alias_resolution_with_posix_root(self, tmp_path):
        """别名说明符在 POSIX 绝对根下必须解析到绝对路径。"""
        ctx = _ctx(tmp_path, {"frontend/src/app/main.tsx": ""})
        ctx.root = Path("/repo")
        files = {"/repo/frontend/src/app/x.ts"}
        resolved = frontend._resolve_spec(
            ctx, "@/app/x", "/repo/frontend/src/app/main.tsx", files)
        assert resolved == "/repo/frontend/src/app/x.ts"

    def test_relative_resolution_with_posix_root(self, tmp_path):
        """相对说明符在 POSIX 绝对根下必须解析到绝对路径。"""
        ctx = _ctx(tmp_path, {"frontend/src/app/main.tsx": ""})
        ctx.root = Path("/repo")
        files = {"/repo/frontend/src/app/components/x.tsx"}
        resolved = frontend._resolve_spec(
            ctx, "./components/x", "/repo/frontend/src/app/main.tsx", files)
        assert resolved == "/repo/frontend/src/app/components/x.tsx"


# ── CL-12 过时类方法 ───────────────────────────────────────────────

class TestDeadMethods:
    """CL-12：类方法零引用（含词边界匹配与同名实体区分）。"""

    def test_reports_zero_reference_method(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                def used(self):
                    return 1

                def dead(self):
                    return 2


            def main():
                return Store().used()
        """})
        rules = _rules(dead_methods.detect(ctx))
        assert [f.symbol for f in rules["CL-12"]] == ["Store.dead"]

    def test_ignores_self_call(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                def outer(self):
                    return self.inner()

                def inner(self):
                    return 1


            def main():
                return Store().outer()
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_dunder(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                def __repr__(self):
                    return "store"
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_framework_decorated(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                @property
                def size(self):
                    return 0

                @staticmethod
                def make():
                    return Store()
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_class_with_dynamic_access(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                def dead(self):
                    return getattr(self, "_x", None)
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_framework_base(self, tmp_path):
        ctx = _ctx(tmp_path, {"m.py": """
            class Store(Protocol):
                def dead(self):
                    return 1
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_declared_compat_noop(self, tmp_path):
        """显式声明为 deprecated no-op 的兼容方法不是清理对象。"""
        ctx = _ctx(tmp_path, {"m.py": """
            class Store:
                def close_thread_cached_connections(self) -> None:
                    \"\"\"Deprecated no-op（线程缓存已移除，保留以兼容旧调用点）。\"\"\"
                    return None
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_stub_path(self, tmp_path):
        ctx = _ctx(tmp_path, {"vendor/stub/mod.py": """
            class SessionOptions:
                def setServerHost(self, host):
                    self._host = host
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_ignores_test_dir(self, tmp_path):
        ctx = _ctx(tmp_path, {"tests/test_m.py": """
            class Helper:
                def dead(self):
                    return 1
        """})
        assert "CL-12" not in _rules(dead_methods.detect(ctx))

    def test_word_boundary_does_not_shadow(self, tmp_path):
        """CL-12 回归：`get_x` 不得被 `get_x_y` 子串遮蔽。"""
        ctx = _ctx(tmp_path, {
            "a.py": """
                class Store:
                    def get_x(self):
                        return 1
            """,
            "b.py": """
                def get_x_y():
                    return 2


                RESULT = get_x_y()
            """,
        })
        rules = _rules(dead_methods.detect(ctx))
        assert [f.symbol for f in rules["CL-12"]] == ["Store.get_x"]

    def test_same_name_module_symbol_not_counted(self, tmp_path):
        """CL-12 回归：同名模块级函数的裸调用不得计为本方法的引用。"""
        ctx = _ctx(tmp_path, {
            "a.py": """
                class Store:
                    def probe(self):
                        return 1
            """,
            "b.py": """
                def probe(mgr):
                    return mgr


                RESULT = probe(1)
            """,
        })
        rules = _rules(dead_methods.detect(ctx))
        assert [f.symbol for f in rules["CL-12"]] == ["Store.probe"]

    def test_same_name_attribute_access_counts(self, tmp_path):
        """同名仅作属性访问时必须计为引用（保守不报）。"""
        ctx = _ctx(tmp_path, {
            "a.py": """
                class Store:
                    def probe(self):
                        return 1
            """,
            "b.py": """
                def probe(mgr):
                    return mgr


                class Other:
                    def go(self, obj):
                        return obj.probe()
            """,
        })
        symbols = [f.symbol for f in _rules(dead_methods.detect(ctx)).get("CL-12", [])]
        assert "Store.probe" not in symbols

    def test_long_method_is_medium(self, tmp_path):
        body = "\n".join("        x%d = %d" % (i, i) for i in range(12))
        ctx = _ctx(tmp_path, {"m.py": "class Store:\n    def dead(self):\n%s\n    \n" % body})
        rules = _rules(dead_methods.detect(ctx))
        assert rules["CL-12"][0].severity.value == "medium"
        assert rules["CL-12"][0].est_effort_h == 0.5


# ── CI 摘要渲染 ────────────────────────────────────────────────────

class TestSummary:
    """`cleanup/summary.py`：JSON → Markdown 摘要（CI Job Summary 消费）。"""

    def test_renders_counts_and_cleanup_rows(self):
        from scripts.cleanup import summary

        payload = {
            "files_scanned": 380,
            "duration_s": 3.68,
            "findings": [
                {"rule_id": "CL-12", "file": "a.py", "line": 7,
                 "symbol": "C.dead", "message": "过时类方法"},
                {"rule_id": "PF-02", "file": "b.py", "line": 9,
                 "symbol": "<loop>", "message": "嵌套循环"},
            ],
        }
        text = "\n".join(summary.render(payload))
        assert "**1**" in text and "| 1 |" in text
        assert "`a.py:7`" in text and "`C.dead`" in text
        assert "| 380 |" in text

    def test_reports_zero_cleanup(self):
        from scripts.cleanup import summary

        text = "\n".join(summary.render({"findings": []}))
        assert "清理项为 0" in text

    def test_truncates_long_lists(self):
        from scripts.cleanup import summary

        payload = {"findings": [
            {"rule_id": "CL-02", "file": "f.py", "line": i, "symbol": "s", "message": "m"}
            for i in range(summary.MAX_ROWS + 3)]}
        text = "\n".join(summary.render(payload))
        assert "（其余 3 项见报告产物）" in text

    def test_missing_file_does_not_fail(self, tmp_path, capsys):
        from scripts.cleanup import summary

        assert summary.main([str(tmp_path / "absent.json")]) == 0
        assert "未读取到" in capsys.readouterr().out


# ── CLI 基线写入口径 ───────────────────────────────────────────────


def test_partial_ruleset_scan_not_recorded(tmp_path, monkeypatch):
    """规则集过滤扫描不得写入趋势库（否则「环比上次全量」出现虚假 0 项基准）。"""
    from scripts.cleanup import cli, config as cli_config
    from scripts.quality_gate.store import GateStore

    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(cli_config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(cli_config, "DB_PATH", tmp_path / "cleanup.db")

    assert cli.main(["--ruleset", "cl", "--quiet"]) == 0
    store = GateStore(cli_config.DB_PATH)
    try:
        assert store.last_full_scan() is None      # 部分扫描不留趋势记录
    finally:
        store.close()

    assert cli.main(["--quiet"]) == 0              # 全量 + 全规则集才记录
    store = GateStore(cli_config.DB_PATH)
    try:
        assert store.last_full_scan() is not None
    finally:
        store.close()
