"""前端模块拓扑漂移守卫（唯一真相源 = ``scripts/module_layout.py``）。

检测内容
--------

1. ``frontend/vite.config.ts`` / ``frontend/vite.base.ts`` 的 ``resolve.alias``
   与 ``module_layout.FRONTEND_ALIASES`` 是否一致；
2. ``frontend/tsconfig.app.json`` 的 ``paths`` 与同一份别名表是否一致；
3. 各模块源码根、各前端扫描根在磁盘上是否存在（可选模块除外）；
4. 与 ``platform_data`` 的模块边界注册表（``contracts`` 子包）声明的模块 id 是否对齐。

为什么需要它
------------

"某个模块的源码在哪个目录"此前散落 4 处（gate 配置 / cleanup 配置 / audit 脚本 / 边界测试），
迁移模块时漏改的后果是**静默的**：模块在 import 图里不可达 ⇒ OE-01、CL-10 批量误报；
边界规则匹配不到任何文件 ⇒ 守卫形同关闭而 CI 依然全绿。
docs/archive/2026-09-21/017-frontend-topology-single-source 将事实收敛为一份，
本文件负责让"收敛后不再漂移"这件事可被机器验证。

执行: pytest backend/api/tests/boundaries/test_frontend_module_layout.py -v
"""
from __future__ import annotations

import posixpath
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.module_layout import (  # noqa: E402
    FRONTEND_ALIASES,
    FRONTEND_SCAN_ROOTS,
    MODULE_LAYOUTS,
    MODULE_ROOTS,
)

RULE_ID = "TOPO-DRIFT"
FRONTEND_DIR = "frontend"

# vite：'@name': path.resolve(__dirname, '<相对 frontend 的路径>')
_VITE_ALIAS_RE = re.compile(
    r"""['"](@[\w-]*)['"]\s*:\s*path\.resolve\(\s*__dirname\s*,\s*['"]([^'"]+)['"]\s*\)"""
)
# tsconfig：'@name/*': ['./相对 frontend 的路径/*']
_TSCONFIG_PATHS_RE = re.compile(r'"(@[\w-]*)/\*"\s*:\s*\[\s*"([^"]+)"')

_VITE_CONFIGS = ("vite.config.ts", "vite.base.ts")
_TSCONFIG = "tsconfig.app.json"


def _repo_relative(raw: str) -> str:
    """把「相对 frontend/ 的路径」归一化为仓库根相对 posix 路径。"""
    target = raw[:-2] if raw.endswith("/*") else raw
    return posixpath.normpath(posixpath.join(FRONTEND_DIR, target))


def _declared_vite_aliases(config_rel: str) -> dict[str, str]:
    """抽取 vite 配置里声明的 alias → 仓库根相对路径。"""
    text = (REPO_ROOT / FRONTEND_DIR / config_rel).read_text(encoding="utf-8")
    return {name: _repo_relative(rel) for name, rel in _VITE_ALIAS_RE.findall(text)}


def _declared_tsconfig_aliases() -> dict[str, str]:
    """抽取 tsconfig.app.json 的 paths → 仓库根相对路径。"""
    text = (REPO_ROOT / FRONTEND_DIR / _TSCONFIG).read_text(encoding="utf-8")
    return {name: _repo_relative(rel) for name, rel in _TSCONFIG_PATHS_RE.findall(text)}


def _diff(declared: dict[str, str], expected: dict[str, str]) -> list[str]:
    """比较两份别名表，返回可读差异清单。"""
    return [
        f"{name}: 配置={declared.get(name)!r} vs module_layout={expected.get(name)!r}"
        for name in sorted(set(declared) | set(expected))
        if declared.get(name) != expected.get(name)
    ]


@pytest.mark.boundary_violation
@pytest.mark.parametrize("config_rel", _VITE_CONFIGS)
def test_vite_aliases_match_single_source(
    violations_recorder, enforcement_mode, config_rel
):
    """vite 配置的 resolve.alias 必须与 module_layout.FRONTEND_ALIASES 一致。"""
    diffs = _diff(_declared_vite_aliases(config_rel), dict(FRONTEND_ALIASES))
    if not diffs:
        return
    violations_recorder(
        RULE_ID,
        f"{FRONTEND_DIR}/{config_rel}",
        "路径别名与 scripts/module_layout.py 不一致：" + "; ".join(diffs),
        fix_hint="同步 frontend/vite.config.ts、frontend/vite.base.ts、"
                 "frontend/tsconfig.app.json 与 scripts/module_layout.py",
    )
    if enforcement_mode == "block":
        pytest.fail(f"{RULE_ID}: {config_rel} 别名漂移 → " + "; ".join(diffs))
    pytest.skip("violation recorded")


@pytest.mark.boundary_violation
def test_tsconfig_paths_match_single_source(violations_recorder, enforcement_mode):
    """tsconfig.app.json 的 paths 必须与 module_layout.FRONTEND_ALIASES 一致。"""
    diffs = _diff(_declared_tsconfig_aliases(), dict(FRONTEND_ALIASES))
    if not diffs:
        return
    violations_recorder(
        RULE_ID,
        f"{FRONTEND_DIR}/{_TSCONFIG}",
        "paths 与 scripts/module_layout.py 不一致：" + "; ".join(diffs),
        fix_hint="同步 frontend/tsconfig.app.json 与 scripts/module_layout.py",
    )
    if enforcement_mode == "block":
        pytest.fail(f"{RULE_ID}: {_TSCONFIG} paths 漂移 → " + "; ".join(diffs))
    pytest.skip("violation recorded")


@pytest.mark.boundary_violation
def test_module_roots_exist(violations_recorder, enforcement_mode):
    """已登记的模块源码根必须真实存在（optional 模块除外）。"""
    missing = [
        f"{m.module_id} → {rel}"
        for m in MODULE_LAYOUTS
        if not m.optional
        for rel in ([m.root] + ([m.standalone_root] if m.standalone_root else []))
        if not (REPO_ROOT / rel).is_dir()
    ]
    if not missing:
        return
    for item in missing:
        violations_recorder(
            RULE_ID,
            item.split(" → ")[1],
            f"module_layout 登记的模块源码根不存在（{item}）",
            fix_hint="迁移模块时同步 scripts/module_layout.py；已迁出本仓库的模块标 optional=True",
        )
    if enforcement_mode == "block":
        pytest.fail(f"{RULE_ID}: 模块源码根缺失 → " + "; ".join(missing))
    pytest.skip("violation recorded")


@pytest.mark.boundary_violation
def test_frontend_scan_roots_exist(violations_recorder, enforcement_mode):
    """前端扫描根必须真实存在（否则前端检测器静默退化为只扫壳层）。"""
    missing = [r for r in FRONTEND_SCAN_ROOTS if not (REPO_ROOT / r).is_dir()]
    if not missing:
        return
    for rel in missing:
        violations_recorder(
            RULE_ID,
            rel,
            "前端扫描根不存在",
            fix_hint="同步 scripts/module_layout.py（FRONTEND_SCAN_ROOTS 由其派生）",
        )
    if enforcement_mode == "block":
        pytest.fail(f"{RULE_ID}: 前端扫描根缺失 → " + "; ".join(missing))
    pytest.skip("violation recorded")


@pytest.mark.boundary_violation
def test_modules_with_boundary_rules_have_scan_root(violations_recorder, enforcement_mode):
    """声明了 forbidden_imports 的模块必须有源码根，否则该规则匹配不到任何文件。"""
    # 模块清单来自审计脚本的 helper（注册表只在那里导入）—— 本文件位于 backend/ 扫描范围内，
    # 直接 import 注册表的模块全路径会被 AP-08 规则命中
    from scripts.audit_cross_imports import modules_requiring_scan

    missing = sorted(modules_requiring_scan() - set(MODULE_ROOTS))
    if not missing:
        return
    for module_id in missing:
        violations_recorder(
            RULE_ID,
            "scripts/module_layout.py",
            f"模块 {module_id} 声明了 forbidden_imports，但未在 module_layout 登记源码根"
            "（其边界规则不会命中任何文件）",
            fix_hint="在 scripts/module_layout.py 的 MODULE_LAYOUTS 追加该模块",
        )
    if enforcement_mode == "block":
        pytest.fail(f"{RULE_ID}: 缺扫描根的边界模块 → " + ", ".join(missing))
    pytest.skip("violation recorded")
