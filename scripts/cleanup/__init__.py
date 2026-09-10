"""代码清理与性能门禁（Cleanup Gate）。

两类规则：
- ``CL-xx`` 清理规则：冗余文件 / 过时符号 / 无用逻辑 / 注释代码
- ``PF-xx`` 性能规则：高耗时 / 高内存热点候选

设计原则：复用 ``scripts/quality_gate`` 的 AST 工具、Finding 模型、SQLite 基线与评分，
只新增检测器与 CLI，不重建框架（自反性约束：监测机制本身不得成为过度工程）。
判定一律「零误报优先」——静态不可证实的场景降级为候选并提示人工确认。
"""

from __future__ import annotations

__all__ = ["config", "reporter"]
