#!/usr/bin/env python
"""EMSXView 质量门禁 — 平铺入口（项目 scripts/ 惯例，同 audit_*.py）。

用法::

    python scripts/quality_gate.py                 # 全量扫描
    python scripts/quality_gate.py --report        # 全量扫描 + Markdown 报告
    python scripts/quality_gate.py --staged        # 增量模式（pre-commit，stdin 文件列表）
    python scripts/quality_gate.py --ruleset ap    # 仅 AP 契约审计
    python scripts/quality_gate.py --suppress <fp> --note "理由"
"""

from __future__ import annotations

import sys
from pathlib import Path

# 支持直接运行（python scripts/quality_gate.py）与包导入两种方式
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from scripts.quality_gate.run import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
