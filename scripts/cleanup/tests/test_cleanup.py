"""清理门禁检测器单测 — 人造 fixture 验证「命中」与「不误报」两侧。

运行：``python -m pytest scripts/cleanup/tests/ -v``
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.cleanup.detectors import dead_files, dead_logic, dead_symbols, frontend, perf
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
