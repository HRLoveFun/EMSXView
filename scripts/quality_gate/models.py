"""质量门禁统一数据模型。

AP-xx（契约违规）与 OE-xx（过度工程）两类规则共用 ``Finding`` 结构，
``ruleset`` 字段区分门禁策略：AP=block（立即阻断）/ OE=guard（基线演进）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """违规严重度等级。"""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RuleSet(str, Enum):
    """规则集：AP=契约违规（确定性），OE=过度工程（启发式）。"""

    AP = "ap"
    OE = "oe"


# severity → 评分权重（OE 量化模型用）
SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.LOW: 1.0,
    Severity.MEDIUM: 2.0,
    Severity.HIGH: 3.0,
}


@dataclass
class Finding:
    """单条检测结果（两类规则集共用）。"""

    rule_id: str                 # 规则编号，如 "AP-01" / "OE-05"
    ruleset: RuleSet             # 所属规则集
    severity: Severity           # 严重度
    file: str                    # 仓库相对路径（posix 风格）
    line: int                    # 1-based 行号；无法定位时为 0
    symbol: str                  # 函数 / 类 / 模块名
    message: str                 # 问题描述
    fix_hint: str                # 重构建议
    fingerprint: str             # 跨扫描追踪标识（sha1）
    est_effort_h: float = 0.0    # 预估重构工时（小时）；AP 规则不计工时

    def is_new(self, known: set[str]) -> bool:
        """是否为基线外新增（OE guard 门禁判定）。"""
        return self.fingerprint not in known


@dataclass
class ScanResult:
    """一次扫描的完整结果。"""

    trigger: str                            # "manual" | "commit"
    mode: str                               # "full" | "staged"
    git_sha: str = ""
    branch: str = ""
    python_loc: int = 0                     # 扫描范围 Python 物理行数（评分分母）
    files_scanned: int = 0
    duration_s: float = 0.0
    findings: list[Finding] = field(default_factory=list)

    @property
    def ap_findings(self) -> list[Finding]:
        """AP 规则集结果。"""
        return [f for f in self.findings if f.ruleset is RuleSet.AP]

    @property
    def oe_findings(self) -> list[Finding]:
        """OE 规则集结果。"""
        return [f for f in self.findings if f.ruleset is RuleSet.OE]

    @property
    def td_hours(self) -> float:
        """技术债总工时（小时，仅 OE 计入）。"""
        return round(sum(f.est_effort_h for f in self.oe_findings), 2)
