"""跨模块 deep import 审计 (AP-01)。

检测规则从 ``platform_data.contracts.boundary_registry`` 的
``forbidden_imports`` 声明**生成** — 新增模块契约后自动纳入检测,
无需修改本脚本。

用法::

    python scripts/audit_cross_imports.py            # 全部规则
    python scripts/audit_cross_imports.py --module backend_api   # 单模块
    python scripts/audit_cross_imports.py --json    # JSON 输出 (CI 友好)

退出码: 0=无违规, 1=存在违规
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# Windows 控制台 (cp1252) 下强制 UTF-8 stdout, 避免中文审计输出抛 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from platform_data.contracts.boundary_registry import boundary_registry  # noqa: E402

# 模块 id → (扫描根, 文件后缀) 映射; 新增模块时在此追加一行
MODULE_SCAN_ROOTS: dict[str, list[tuple[Path, str]]] = {
    "frontend_execution": [(REPO_ROOT / "frontend" / "src" / "modules" / "execution", "*.tsx"),
                            (REPO_ROOT / "frontend" / "src" / "modules" / "execution", "*.ts")],
    "frontend_costview": [(REPO_ROOT / "frontend" / "src" / "modules" / "costview", "*.tsx"),
                           (REPO_ROOT / "frontend" / "src" / "modules" / "costview", "*.ts")],
    "frontend_marketview": [(REPO_ROOT / "frontend" / "src" / "modules" / "marketview", "*.tsx"),
                             (REPO_ROOT / "frontend" / "src" / "modules" / "marketview", "*.ts")],
    "frontend_databaseview": [(REPO_ROOT / "frontend" / "src" / "modules" / "databaseview", "*.tsx"),
                               (REPO_ROOT / "frontend" / "src" / "modules" / "databaseview", "*.ts")],
    "backend_api": [(REPO_ROOT / "backend" / "api", "*.py")],
    "costview_src": [(REPO_ROOT / "CostView" / "src", "*.py")],
    "datapipeline": [(REPO_ROOT / "DataPipeline", "*.py")],
}

# 豁免清单 (posix 相对路径): 设计内受许可的深导入 (DI 注册/桥接入口)
EXEMPTIONS: dict[str, set[str]] = {
    "backend_api": {
        "backend/api/main.py",  # 启动时向 config_bridge 注册 DataPipeline Config
    },
    "costview_src": set(),
    "datapipeline": set(),
    "frontend_execution": set(),
    "frontend_costview": set(),
    "frontend_marketview": set(),
    "frontend_databaseview": set(),
}


def _scan_python_imports(text: str) -> list[str]:
    return re.findall(r"^\s*from\s+([\w.]+)\s+import", text, flags=re.MULTILINE)


def _scan_ts_imports(text: str) -> list[str]:
    return re.findall(r"from\s+['\"]([^'\"]+)['\"]", text)


def run_audit(module_filter: str | None = None) -> list[dict]:
    """执行审计, 返回违规列表 [{module, path, import_name, forbidden}]。"""
    violations: list[dict] = []
    contracts = boundary_registry.all_contracts()
    if module_filter:
        contracts = [c for c in contracts if c.module_id == module_filter]

    for contract in contracts:
        if not contract.forbidden_imports:
            continue
        scan_roots = MODULE_SCAN_ROOTS.get(contract.module_id, [])
        exempt = EXEMPTIONS.get(contract.module_id, set())
        for base_dir, suffix in scan_roots:
            if not base_dir.exists():
                continue
            scanner = _scan_python_imports if suffix == "*.py" else _scan_ts_imports
            for file_path in base_dir.rglob(suffix):
                rel = file_path.relative_to(REPO_ROOT).as_posix()
                if rel in exempt:
                    continue
                try:
                    text = file_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                for imp in scanner(text):
                    if any(imp.startswith(f) for f in contract.forbidden_imports):
                        violations.append({
                            "module": contract.module_id,
                            "path": rel,
                            "import_name": imp,
                            "forbidden": next(
                                f for f in contract.forbidden_imports
                                if imp.startswith(f)
                            ),
                        })
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="跨模块 deep import 审计 (AP-01)")
    parser.add_argument("--module", help="仅审计指定模块 id")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    violations = run_audit(args.module)

    if args.json:
        print(json.dumps({"violations": violations}, ensure_ascii=False, indent=2))
    elif violations:
        print(f"[AP-01] 发现 {len(violations)} 处跨模块 deep import 违规:")
        for v in violations:
            print(f"  {v['path']}: import '{v['import_name']}' "
                  f"(模块 {v['module']} 禁止 {v['forbidden']}*)")
    else:
        scope = f" (模块 {args.module})" if args.module else ""
        print(f"[AP-01] 跨模块 import 审计通过{scope}, 无违规")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
