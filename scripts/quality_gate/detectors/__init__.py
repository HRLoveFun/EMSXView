"""检测器注册表 — full / staged 两档可用性。

- full：全部检测器（手动触发或报告生成）
- staged：仅快速检测器（pre-commit 增量快检，受时间预算保护）
  死模块 / 过度抽象 / 设计模式 / 重复块需全库 AST 索引，留待全量扫描
"""

from __future__ import annotations

from typing import Callable

from ..context import ScanContext
from ..models import Finding

# 检测器统一签名
Detector = Callable[[ScanContext], list[Finding]]

from . import ap_adapter, complexity, dead_modules, duplication  # noqa: E402
from . import frontend_light, needless_patterns, over_abstraction  # noqa: E402

# 全量模式检测器（顺序即执行顺序：AP 契约优先，再 OE 按影响排序）
FULL_DETECTORS: list[Detector] = [
    ap_adapter.detect,          # AP-01/04/08（包装既有审计脚本）
    complexity.detect,          # OE-05 复杂度超标
    duplication.detect,         # OE-04 重复代码块
    over_abstraction.detect,    # OE-02 过度抽象
    needless_patterns.detect,   # OE-03 不必要设计模式
    dead_modules.detect,        # OE-01 冗余模块
    frontend_light.detect,      # OE-06/07 前端轻量检测
]

# 增量模式检测器（staged 文件级快检 + 全库文本级检测）
STAGED_DETECTORS: list[Detector] = [
    ap_adapter.detect,          # 全库正则（与既有 hook 行为一致）
    complexity.detect,          # staged py 文件
    frontend_light.detect,      # 全库 import 图 + staged 文件判定
]
