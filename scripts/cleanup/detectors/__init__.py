"""清理门禁检测器注册表。

执行顺序：先文件级（删除收益最大、人工成本最低），再符号级，再逻辑级，最后性能级。
所有检测器共享 ``ScanContext``，统一返回 ``list[Finding]``。
"""

from __future__ import annotations

from typing import Callable

from scripts.quality_gate.context import ScanContext
from scripts.quality_gate.models import Finding

from . import dead_files, dead_logic, dead_symbols, frontend, perf

Detector = Callable[[ScanContext], list[Finding]]

# 规则集 → 检测器（--ruleset cl / pf 过滤用）
CL_DETECTORS: list[Detector] = [
    dead_files.detect,      # CL-01 / CL-07 / CL-08
    dead_symbols.detect,    # CL-02
    dead_logic.detect,      # CL-03 / CL-04 / CL-05 / CL-06 / CL-09
    frontend.detect_cleanup,  # CL-10
]

PF_DETECTORS: list[Detector] = [
    perf.detect,              # PF-01 ~ PF-06
    frontend.detect_perf,     # PF-07 / PF-08
]

FULL_DETECTORS: list[Detector] = [*CL_DETECTORS, *PF_DETECTORS]

__all__ = ["Detector", "CL_DETECTORS", "PF_DETECTORS", "FULL_DETECTORS"]
