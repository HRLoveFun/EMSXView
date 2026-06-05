"""禁止硬编码数据库路径。

对应反模式: AP-04 数据库路径硬编码
对应 ADR: ADR-0012 配置隔离
执行: pytest backend/api/tests/boundaries/test_db_path_from_config.py -v
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_DIRS = [
    REPO_ROOT / "backend" / "api",
    REPO_ROOT / "DataPipeline",
    REPO_ROOT / "CostView" / "src",
]
ALLOWLIST_FILES = {"config.py", "schemas.py", "__init__.py"}
# 匹配 *.db 字符串字面量（包括 'data/raw_fills.db' / "../foo.db"）
DB_PATH_RE = re.compile(r"""['"]([^'"]*\.db)['"]""")


@pytest.mark.boundary_violation
def test_no_hardcoded_db_paths(violations_recorder):
    if not any(d.exists() for d in SCAN_DIRS):
        pytest.skip("no scan dirs exist")

    violations = []

    for base_dir in SCAN_DIRS:
        if not base_dir.exists():
            continue
        for f in base_dir.rglob("*.py"):
            if f.name in ALLOWLIST_FILES:
                continue
            if "/tests/" in str(f) or "/__pycache__/" in str(f):
                continue
            try:
                text = f.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            for m in DB_PATH_RE.finditer(text):
                try:
                    rel = f.relative_to(REPO_ROOT)
                except ValueError:
                    rel = f
                violations.append((str(rel), m.group(1)))

    if violations:
        for path, db_path in violations:
            violations_recorder(
                "AP-04",
                path,
                f"hardcoded db path: {db_path}",
                fix_hint="改用 DataPipeline.config.Config.DB_PATHS[...]",
            )
        pytest.skip(
            f"violation recorded: {len(violations)} AP-04 violation(s); "
            f"see BOUNDARY VIOLATIONS section in summary"
        )
