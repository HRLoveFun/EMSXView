"""质量门禁配置 — 阈值 / 扫描范围 / 豁免 / 门禁模式。

唯一真相源：所有检测阈值集中于此，调优只改本文件。
"""

from __future__ import annotations

from pathlib import Path

from .ast_utils import find_project_root

# 项目根（.emsxview-root marker，AP-16 单一信息源）
PROJECT_ROOT: Path = find_project_root(Path(__file__))

# ── 扫描范围（Python 业务代码根，相对 PROJECT_ROOT）───────────────
PYTHON_SCAN_ROOTS: list[str] = [
    "backend/api",
    "DataPipeline",
    "CostView/src",
    "platform_data",
    "MarketView",
]
FRONTEND_SCAN_ROOT: str = "frontend/src"

# 全库收集时排除的目录名（import 图 / 调用计数仍覆盖业务目录）
GLOBAL_EXCLUDE_DIRS: set[str] = {
    "__pycache__", ".venv", "venv", "node_modules", ".git",
    ".codebuddy", ".specify", ".githooks", "dist", "build", ".pytest_cache",
}

# ── OE-01 死模块：入口白名单 ──────────────────────────────────────
# 命中即视为图入口（有外部触发方：CLI / pytest / 部署器）
ENTRY_FILE_NAMES: set[str] = {"main.py", "__main__.py", "conftest.py", "setup.py"}
ENTRY_DIR_PARTS: set[str] = {"scripts", "tests", "test", "docs", "specs", "plans"}

# OE 通用目录豁免（测试代码复杂度 / 抽象是常态，不判定）
OE_EXEMPT_DIR_PARTS: set[str] = {"tests", "test", "__pycache__"}

# OE-01 额外豁免清单（posix 相对路径）— 动态加载等无法静态追踪的场景，人工审定
DEAD_MODULE_EXEMPT: set[str] = set()

# ── OE-02 过度抽象阈值 ────────────────────────────────────────────
MAX_SINGLE_IMPL_LOC: int = 50       # 单实现抽象类的唯一实现行数上限

# ── OE-03 设计模式阈值 ────────────────────────────────────────────
MAX_INHERIT_DEPTH: int = 3          # 继承链最大边数（D→C→B→A 为 3 边；超过即报）

# ── OE-04 重复块阈值 ──────────────────────────────────────────────
MIN_DUPLICATION_LINES: int = 30     # 归一化后行数达到该值才参与整函数匹配
# 重复检测额外豁免的路径片段（数据迁移/回填脚本天然雷同）
DUPLICATION_EXEMPT_PARTS: tuple[str, ...] = ("backfill", "migrate", "ops/", "schema/")

# ── OE-05 复杂度阈值 ──────────────────────────────────────────────
MAX_CYCLOMATIC: int = 15            # 圈复杂度上限（超出为 medium）
MAX_CYCLOMATIC_HIGH: int = 30       # 圈复杂度严重上限（超出为 high）
MAX_NESTING: int = 4                # 嵌套深度上限
MAX_PARAMS: int = 7                 # 参数个数上限
MAX_FUNC_LINES: int = 120           # 函数长度上限

# ── OE-06/07 前端阈值 ─────────────────────────────────────────────
MAX_COMPONENT_LINES: int = 400      # tsx 文件行数上限
MAX_USE_STATE: int = 10             # 单文件 useState 计数上限
# 前端入口/框架文件豁免（注册表入口与类型声明，导出无消费者是设计使然）
FRONTEND_EXEMPT_FILES: set[str] = {
    "src/module.registry.ts",
    "src/main.tsx",
    "src/vite-env.d.ts",
}
# 前端路径别名映射（来源 vite.config.ts resolve.alias；漂移需同步此表）
# 值为相对 frontend/src 的 posix 路径（别名挂载点在 frontend/src，非仓库根）
FRONTEND_ALIASES: dict[str, str] = {
    "@": "",
    "@app": "app",
    "@shared": "shared",
    "@execution": "modules/execution",
    "@costview": "modules/costview",
    "@marketview": "modules/marketview",
    "@databaseview": "modules/databaseview",
}

# ── 门禁模式 ──────────────────────────────────────────────────────
# AP: block — 任何 AP 违规立即阻断（与既有 pre-commit 行为一致）
# OE: guard — 基线演进：新增阻断 / 存量放行 / 修复正向提示
AP_ENFORCEMENT: str = "block"
OE_ENFORCEMENT: str = "guard"

# ── 性能预算 ──────────────────────────────────────────────────────
STAGED_TIME_BUDGET_S: float = 25.0  # 增量模式检测器共享预算（秒），超出 fail-open

# ── 产出路径 ──────────────────────────────────────────────────────
REPORT_DIR: Path = PROJECT_ROOT / "scripts" / "reports" / "quality_gate"
DB_PATH: Path = REPORT_DIR / "quality_gate.db"
