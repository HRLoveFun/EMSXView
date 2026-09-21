"""模块拓扑的唯一真相源 —— 模块源码根 / 前端扫描根 / 前端路径别名。

为什么单独成文件
----------------

「某个模块的源码在哪个目录」这一事实，此前散落在 4 处：

1. ``scripts/quality_gate/config.py`` —— ``FRONTEND_SCAN_ROOTS`` + ``FRONTEND_ALIASES``
2. ``scripts/cleanup/config.py`` —— 同名前端扫描根（字面复制，且**实际未被使用**，
   见 docs/archive/2026-09-21/017-frontend-topology-single-source）
3. ``scripts/audit_cross_imports.py`` —— ``MODULE_SCAN_ROOTS`` 硬编码绝对路径
4. ``backend/api/tests/boundaries/test_cross_module_imports.py`` —— 硬编码扫描根

模块迁目录时（如 docs/archive/2026-09-21/012-executionview-root-extract 把 ExecutionView 提到仓库根级、docs/archive/2026-09-21/018-costview-marketview-root-extract 把 costview/marketview
同构平移）四处都要改，而**漏改的后果是静默的**：

- 该模块在 import 图里变成不可达 ⇒ OE-01「死模块」批量误报 / CL-10 误报；
- 边界规则不再命中任何文件 ⇒ 守卫形同关闭（CI 依然全绿）。

故把该事实收敛为一份，其余位置一律派生。本文件是**纯数据 + 纯函数**：不做文件系统探测、
不解析构建配置，供任意消费方（gate / cleanup / audit / pytest）直接导入。

漂移守卫
--------

``backend/api/tests/boundaries/test_frontend_module_layout.py`` 会比对：

- 本文件的别名表 vs ``frontend/vite.config.ts`` / ``frontend/vite.base.ts`` 实际的 ``resolve.alias``；
- 各模块源码根、前端扫描根在磁盘上真实存在；
- 本文件的模块 id 与 ``platform_data.contracts.boundary_registry`` 声明一致。

维护
----

新增 / 迁移前端模块：只改本文件 ``MODULE_LAYOUTS`` 一行，并在**同一次提交**里同步
``frontend/vite.config.ts``、``frontend/vite.base.ts``、``frontend/tsconfig*.json``
（守卫测试会拦下不一致，CI 生效）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleLayout:
    """一个模块的源码布局（路径均为**仓库根相对** posix 路径）。"""

    module_id: str      # 与 platform_data.contracts.boundary_registry 的 module_id 对齐
    root: str           # 源码根目录
    language: str       # "ts"（前端）| "py"（Python）
    alias: str = ""     # 前端路径别名（含 @）；非前端模块留空
    optional: bool = False  # True = 源码已迁出本仓库，目录缺失属预期（扫描器跳过）
    standalone_root: str = ""  # 独立构建入口根（index.html + main.tsx），需纳入扫描以保持 import 图完整


# ── 全部模块（前端 + Python 侧）─────────────────────────────────────
MODULE_LAYOUTS: tuple[ModuleLayout, ...] = (
    # 前端模块：三个业务模块均已独立为仓库根级目录（docs/archive/2026-09-21/012-executionview-root-extract、018-costview-marketview-root-extract）
    ModuleLayout("frontend_execution", "ExecutionView/module", "ts", "@execution",
                 standalone_root="ExecutionView/standalone"),
    ModuleLayout("frontend_costview", "CostView/module", "ts", "@costview",
                 standalone_root="CostView/standalone"),
    ModuleLayout("frontend_marketview", "MarketView/module", "ts", "@marketview",
                 standalone_root="MarketView/standalone"),
    # Python 侧模块
    ModuleLayout("backend_api", "backend/api", "py"),
    ModuleLayout("costview_src", "CostView/src", "py"),
    # DataPipeline 已迁独立仓库（docs/archive/2026-09-21/010-extract-pipeline）：登记保留（optional），
    # 目录缺失属预期；若目录恢复则自动重新纳入扫描
    ModuleLayout("datapipeline", "DataPipeline", "py", optional=True),
)

# ── 前端壳层（Shell 编排 + 共享契约层；独立模块不在其中）─────────────
FRONTEND_SHELL_ROOT: str = "frontend/src"

# 壳层内的固定别名（与模块别名共同构成完整 alias 表）
FRONTEND_SHELL_ALIASES: dict[str, str] = {
    "@": FRONTEND_SHELL_ROOT,
    "@app": "frontend/src/app",
    "@shared": "frontend/src/shared",
}


# ── 派生视图（消费方只读这些）──────────────────────────────────────

MODULE_ROOTS: dict[str, str] = {m.module_id: m.root for m in MODULE_LAYOUTS}

# 模块 id → 扫描后缀（前端同时扫 tsx/ts，Python 只扫 py）
MODULE_GLOBS: dict[str, tuple[str, ...]] = {
    m.module_id: (("*.tsx", "*.ts") if m.language == "ts" else ("*.py",))
    for m in MODULE_LAYOUTS
}

FRONTEND_MODULES: tuple[ModuleLayout, ...] = tuple(m for m in MODULE_LAYOUTS if m.language == "ts")

FRONTEND_ALIASES: dict[str, str] = {
    **FRONTEND_SHELL_ALIASES,
    **{m.alias: m.root for m in FRONTEND_MODULES if m.alias},
}


def _is_subpath(child: str, parent: str) -> bool:
    """``child`` 是否位于 ``parent`` 之下（均为仓库根相对 posix 路径）。"""
    return child == parent or child.startswith(parent.rstrip("/") + "/")


def minimal_roots(roots: list[str]) -> list[str]:
    """去掉被其他根包含的路径，返回最小覆盖集合（用于避免重复扫描同一批文件）。"""
    unique = sorted({r for r in roots if r})
    return [
        r for r in unique
        if not any(other != r and _is_subpath(r, other) for other in unique)
    ]


# 前端扫描根 = 壳层根 + 全部前端模块源码根 + 各自 standalone 入口根。
#
# standalone 入口必须纳入：它们 import 模块注册表与 `@/standalone/shell-less`；
# 漏扫会让**被它们消费的文件**在 import 图里失去消费者 —— 实测（docs/archive/2026-09-21/018-costview-marketview-root-extract）漏扫两个
# standalone 入口后 `frontend/src/standalone/shell-less.tsx` 被误判为「未使用导出」（OE-06 +1）。
FRONTEND_SCAN_ROOTS: list[str] = [FRONTEND_SHELL_ROOT] + [
    r for r in minimal_roots(
        [FRONTEND_SHELL_ROOT]
        + [m.root for m in FRONTEND_MODULES]
        + [m.standalone_root for m in FRONTEND_MODULES if m.standalone_root]
    )
    if r != FRONTEND_SHELL_ROOT
]
