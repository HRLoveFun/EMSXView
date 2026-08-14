"""DB 路径硬编码审计 (AP-04)。

扫描业务代码中的 ``*.db`` 字符串字面量 — DB 路径必须从
``DataPipeline.config.Config`` 读取, 禁止绕过 Config 硬编码。

用法::

    python scripts/audit_db_paths.py
    python scripts/audit_db_paths.py --json

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

# 扫描根: 业务代码目录 (config.py / schemas.py / __init__.py 为豁免文件类型)
SCAN_ROOTS: list[tuple[Path, str]] = [
    (REPO_ROOT / "backend" / "api", "*.py"),
    (REPO_ROOT / "DataPipeline", "*.py"),
    (REPO_ROOT / "CostView" / "src", "*.py"),
    (REPO_ROOT / "platform_data", "*.py"),
]

# 豁免文件 (相对 REPO_ROOT, posix 风格) — 配置层/DDL/常量定义允许引用 .db 名称
EXEMPT_FILES = {
    "DataPipeline/config.py",
    "DataPipeline/storage/connection.py",   # DB 注册表 (从 Config 派生)
    "DataPipeline/storage/schema/inline_ddl.py",
    "DataPipeline/storage/schema/columns.py",
    "platform_data/contracts/db_constants.py",
    # 备份/归档工具的通用文件模式处理 (glob/f-string 模板), 非路径硬编码
    "DataPipeline/storage/backup.py",
    "DataPipeline/storage/archiver.py",
    # CLI 菜单文案 (显示用文件名, 非路径) 与诊断模块 fallback 默认值
    "CostView/src/__main__.py",
    "platform_data/database_diagnostics.py",
}

# 豁免目录: 测试代码允许使用临时 .db 字面量
EXEMPT_DIR_PARTS = ("tests", "test")

# 豁免行模式:
#   - f-string 模板 (运行时拼接)
#   - 日志文案中的 .db 引用
#   - 从 Config.DATA_DIR 派生的字面量 (路径根已由 Config 提供, 符合 AP-04 豁免)
#   - tempfile 后缀参数 (非路径)
_ALLOWED_LINE_PATTERNS = (
    re.compile(r"['\"][^'\"]*\{[^'\"]*\.db"),      # f-string 内嵌 .db
    re.compile(r"\b(logger|logging|print|log)\b"), # 日志文案
    re.compile(r"DATA_DIR\s*[/]\s*['\"]"),         # Config.DATA_DIR 派生
    re.compile(r"suffix\s*=\s*['\"][^'\"]*\.db"),  # tempfile 后缀
)

_DB_LITERAL = re.compile(r"['\"]([^'\"]*\.db)['\"]")


def run_audit() -> list[dict]:
    """返回违规列表 [{path, line, literal}]。"""
    violations: list[dict] = []
    for base_dir, suffix in SCAN_ROOTS:
        if not base_dir.exists():
            continue
        for file_path in base_dir.rglob(suffix):
            rel = file_path.relative_to(REPO_ROOT).as_posix()
            if rel in EXEMPT_FILES:
                continue
            if any(part in EXEMPT_DIR_PARTS for part in file_path.parts):
                continue
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for lineno, line in enumerate(lines, start=1):
                if line.strip().startswith("#"):
                    continue
                if any(p.search(line) for p in _ALLOWED_LINE_PATTERNS):
                    continue
                for m in _DB_LITERAL.finditer(line):
                    violations.append({
                        "path": rel,
                        "line": lineno,
                        "literal": m.group(1),
                    })
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description="DB 路径硬编码审计 (AP-04)")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    violations = run_audit()

    if args.json:
        print(json.dumps({"violations": violations}, ensure_ascii=False, indent=2))
    elif violations:
        print(f"[AP-04] 发现 {len(violations)} 处 DB 路径硬编码:")
        for v in violations:
            print(f"  {v['path']}:{v['line']} -> '{v['literal']}'")
        print("修复: 改用 DataPipeline.config.Config 中的路径属性")
    else:
        print("[AP-04] DB 路径审计通过, 无硬编码")

    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
