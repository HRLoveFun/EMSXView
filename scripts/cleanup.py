#!/usr/bin/env python
"""EMSXView 代码清理与性能热点门禁 — 平铺入口（项目 scripts/ 惯例，同 audit_*.py）。

用法::

    python scripts/cleanup.py                    # 全量扫描（清理 + 性能）
    python scripts/cleanup.py --report           # 全量扫描 + Markdown 报告
    python scripts/cleanup.py --ruleset cl       # 仅清理规则（CL-xx）
    python scripts/cleanup.py --ruleset pf       # 仅性能规则（PF-xx）
    python scripts/cleanup.py --json             # 机器可读输出
    python scripts/cleanup.py --strict           # 新增项即退出码 1（CI 强门禁）
    python scripts/cleanup.py --suppress <fp> --note "理由"
"""

from __future__ import annotations

import sys
from pathlib import Path

# 支持直接运行（python scripts/cleanup.py）与包导入两种方式
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from scripts.cleanup.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
