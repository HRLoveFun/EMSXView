"""校验违规记录数据结构。

定义 ValidationViolation 实体，代表单条数据校验失败的具体信息。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from DataPipeline.validation.enums import SeverityLevel, ViolationType


@dataclass
class ValidationViolation:
    """单条数据校验失败的具体信息。

    对照 data-model.md 第 3 节实体定义。
    """

    # 所属管道运行 ID
    run_id: str
    # 发生违规的阶段名称（如 "S2"）
    stage_name: str
    # 违规字段名
    field_name: str
    # 期望约束描述（如 "type=int, gt=0"）
    expected_constraint: str
    # 实际值
    actual_value: Any
    # 违规严重等级
    severity: SeverityLevel
    # 违规类型
    violation_type: ViolationType
    # 违规记录的主键或行号标识（可选）
    record_identifier: str | None = None
    # 违规发生时间
    violated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __hash__(self) -> int:
        """基于字段内容的哈希值"""
        return hash(
            (self.run_id, self.stage_name, self.field_name,
             self.expected_constraint, str(self.actual_value),
             self.severity, self.violation_type, self.record_identifier)
        )
