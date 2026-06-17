"""管道护栏机制所有枚举类型定义。

对照 data-model.md 枚举定义章节，统一管理所有枚举值。
"""

from enum import Enum


class RunStatus(str, Enum):
    """管道运行状态枚举"""

    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_FAILURE = "partial_failure"
    CIRCUIT_BROKEN = "circuit_broken"
    ABORTED = "aborted"


class StageStatus(str, Enum):
    """阶段执行状态枚举"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CIRCUIT_BROKEN = "circuit_broken"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


class SeverityLevel(str, Enum):
    """异常严重等级枚举

    INFO: 记录可恢复异常，不阻断当前阶段
    ERROR: 阻断当前阶段，不熔断下游
    CRITICAL: 立即熔断全链路并告警
    """

    INFO = "info"
    ERROR = "error"
    CRITICAL = "critical"


class BreakerState(str, Enum):
    """熔断器状态枚举

    CLOSED: 正常运行状态
    HALF_OPEN: 探测模式（允许一个阶段执行以验证恢复）
    OPEN: 完全阻断状态
    """

    CLOSED = "closed"
    HALF_OPEN = "half_open"
    OPEN = "open"


class ViolationType(str, Enum):
    """校验违规类型枚举"""

    MISSING_REQUIRED = "missing_required"
    TYPE_MISMATCH = "type_mismatch"
    RANGE_VIOLATION = "range_violation"
    ENUM_VIOLATION = "enum_violation"
    CUSTOM_CONSTRAINT = "custom_constraint"


class ValidationPolicy(str, Enum):
    """校验策略枚举

    STRICT: 完整校验（类型+值域+必填+定制约束）
    RELAXED: 仅校验类型，允许重试降级
    """

    STRICT = "strict"
    RELAXED = "relaxed"


class SchemaDirection(str, Enum):
    """模式方向枚举"""

    INPUT = "input"
    OUTPUT = "output"


class ContractCompatibility(str, Enum):
    """契约兼容性枚举"""

    COMPATIBLE = "compatible"
    COMPATIBLE_WITH_WARNING = "compatible_with_warning"
    INCOMPATIBLE = "incompatible"
