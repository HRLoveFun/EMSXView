"""策略注册表校验服务（057 DL-16）——提交前参数校验 + 白名单合规检查。

接入点：submission_service.submit_proposal_core 路由前调用。
语义：errors 阻断（注册表硬校验）；warnings 放行 + 审计记录（unmapped 族、
白名单未知、白名单未命中）。白名单未命中 v0 **不阻断**（防误阻断存量路由）——
阻断由 DL-17 硬约束引擎经特性开关启用（G2：新能力默认关闭）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from platform_data.contracts import (
    REGISTRY_VERSION,
    compliance_check,
    load_algo_whitelist,
    resolve_family,
    validate_strategy_params,
)

logger = logging.getLogger(__name__)


@dataclass
class SubmissionValidation:
    """提交前校验结果。errors 非空 → 阻断；warnings 仅记录。"""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    registry_version: str = REGISTRY_VERSION
    whitelist_version: str | None = None


def validate_route_submission(
    broker: str,
    strategy: str,
    params: dict | None = None,
    *,
    whitelist=None,
) -> SubmissionValidation:
    """注册表校验 + 白名单合规检查（whitelist 缺省时按需懒加载一次）。"""
    result = SubmissionValidation()

    # ① 注册表参数校验（errors 阻断）
    result.errors.extend(validate_strategy_params(strategy, params))

    # ② 族归类警告（unmapped 不阻断——broker 专有算法族级归类即可）
    family = resolve_family(strategy)
    if family == "unmapped":
        result.warnings.append(f"strategy {strategy!r} family unmapped (broker-specific algo?)")

    # ③ 白名单合规（配置了才检查；未命中 v0 记 warning 不阻断）
    if whitelist is None:
        whitelist = load_algo_whitelist()
    if whitelist is None:
        result.warnings.append("algo whitelist not configured (compliance check skipped)")
    else:
        result.whitelist_version = f"{whitelist.row_count} brokers @ {whitelist.loaded_at}"
        verdict = compliance_check(whitelist, broker, strategy)
        if not verdict.allowed:
            result.warnings.append(f"algo whitelist: {verdict.reason}")
    return result
