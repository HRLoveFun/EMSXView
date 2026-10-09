"""统一提交服务 (S14/054) —— 单笔与批量建议确认共用同一套提交状态机。

收敛第二份审计发现的缺口：
- batch-confirm 未接入授权校验/建议锁/持久化回写（本服务统一提供）；
- 504/响应丢失后建议回退 PENDING_CONFIRM 允许盲目重发（改为 NEEDS_REVIEW 冻结，
  人工核对后经 resolve 解除）；
- batch 流的 bytes 序列化 TypeError（统一行解码）。

提交状态机：
  PENDING_CONFIRM → CONFIRMING → SUBMITTED
                              → NEEDS_REVIEW（结果未知，冻结）
                              → PENDING_CONFIRM（明确失败，可重试）
  NEEDS_REVIEW → SUBMITTED（resolve: 人工核对确认已成交）
               → REJECTED（resolve: 人工核对确认未成交/放弃）
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class ProposalStatus(str, enum.Enum):
    """建议状态机（与内存 dict / DB status 列共用词汇表）。"""

    PENDING_CONFIRM = "PENDING_CONFIRM"
    CONFIRMING = "CONFIRMING"
    SUBMITTED = "SUBMITTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


@dataclass
class SubmissionResult:
    """单条建议的提交结果（端点层据此组装响应/流行）。"""

    proposal_id: int
    outcome: str  # SUBMITTED / NEEDS_REVIEW / FAILED / BLOCKED
    route_id: Optional[int] = None
    detail: Optional[str] = None
    http_status: Optional[int] = None  # BLOCKED 时携带 403/400


async def submit_proposal_core(
    proposal_id: int,
    proposal: dict,
    bloomberg: Any,
    *,
    correlation_id: str,
    persist_result=None,
    audit_result=None,
    compliance_check=None,
    authorization_check=None,
) -> SubmissionResult:
    """单条建议提交的核心状态机（单笔与批量共用）。

    流程：状态校验 → CONFIRMING → compliance → 授权 → route_order → 终态。
    - 504/结果未知 → NEEDS_REVIEW（冻结，不可重发）+ audit unknown；
    - 明确失败 → PENDING_CONFIRM 回退（可重试）+ audit fail；
    - BLOCKED（compliance/授权拦截）→ 回退 + HTTPException 原样传播。

    persist_result/audit_result/compliance_check/authorization_check 由调用方
    注入（避免本服务与 routers/deps 循环导入）。
    """
    from schemas import RouteOrderRequest

    status = proposal.get("status")
    if status == ProposalStatus.CONFIRMING.value:
        return SubmissionResult(
            proposal_id=proposal_id,
            outcome="BLOCKED",
            detail="already being confirmed",
            http_status=409,
        )
    if status == ProposalStatus.NEEDS_REVIEW.value:
        return SubmissionResult(
            proposal_id=proposal_id,
            outcome="BLOCKED",
            detail="needs manual review — use resolve endpoint",
            http_status=409,
        )
    if status != ProposalStatus.PENDING_CONFIRM.value:
        return SubmissionResult(
            proposal_id=proposal_id,
            outcome="BLOCKED",
            detail=f"status '{status}' not PENDING_CONFIRM",
            http_status=400,
        )

    proposal["status"] = ProposalStatus.CONFIRMING.value
    proposal["updated_at"] = _now()

    # compliance（由调用方注入闭包，保持与单笔入口同口径）
    if compliance_check is not None:
        violations = compliance_check(proposal)
        if violations:
            proposal["status"] = ProposalStatus.PENDING_CONFIRM.value
            if audit_result:
                audit_result(correlation_id, "fail")
            raise HTTPException(
                400,
                detail={
                    "message": "Pre-trade compliance check failed",
                    "violations": [v.model_dump() for v in violations],
                },
            )

    # PM 授权（由调用方注入闭包）
    if authorization_check is not None:
        authz = await authorization_check(proposal)
        if authz and authz.get("outcome") == "exceeded":
            proposal["status"] = ProposalStatus.PENDING_CONFIRM.value
            if audit_result:
                audit_result(correlation_id, "fail")
            raise HTTPException(
                403,
                detail={"message": "PM authorization limit exceeded", **authz},
            )

    try:
        route_req = RouteOrderRequest(
            orderId=proposal["parent_order_id"],
            broker=proposal["broker"],
            quantity=proposal["quantity"],
            orderType=proposal.get("order_type") or "LIMIT",
            price=proposal.get("limit_price"),
            timeInForce=proposal.get("tif") or "DAY",
            strategyParams=proposal.get("strategy_params"),
        )
        result = await bloomberg.route_order(route_req)
        route_id = result.get("routeId") if isinstance(result, dict) else None

        now = _now()
        proposal.update(
            status=ProposalStatus.SUBMITTED.value,
            route_id=route_id,
            confirmed_at=now,
            submitted_at=now,
            updated_at=now,
        )
        if persist_result:
            await persist_result(proposal_id, status=ProposalStatus.SUBMITTED.value,
                                 route_id=route_id, confirmed_at=now, submitted_at=now)
        if audit_result:
            audit_result(correlation_id, "ok")
        return SubmissionResult(proposal_id=proposal_id, outcome="SUBMITTED", route_id=route_id)

    except HTTPException as exc:
        if exc.status_code == 504:
            # 结果未知 (S14/054)：券商可能已收到订单——冻结待人工核对，
            # 不得盲目重发。解除路径：resolve 端点。返回结果（不 re-raise），
            # 端点层组装「outcome unknown」响应。
            proposal["status"] = ProposalStatus.NEEDS_REVIEW.value
            if persist_result:
                await persist_result(proposal_id, status=ProposalStatus.NEEDS_REVIEW.value)
            if audit_result:
                audit_result(correlation_id, "unknown")
            return SubmissionResult(
                proposal_id=proposal_id,
                outcome="NEEDS_REVIEW",
                detail=str(exc.detail),
            )
        proposal["status"] = ProposalStatus.PENDING_CONFIRM.value
        if audit_result:
            audit_result(correlation_id, "fail")
        raise
    except Exception:
        logger.exception("Failed to submit proposal %d", proposal_id)
        proposal["status"] = ProposalStatus.PENDING_CONFIRM.value
        if persist_result:
            try:
                await persist_result(proposal_id, status=ProposalStatus.PENDING_CONFIRM.value)
            except Exception:
                logger.error("Proposal %d failure write-back failed", proposal_id)
        if audit_result:
            audit_result(correlation_id, "fail")
        return SubmissionResult(
            proposal_id=proposal_id,
            outcome="FAILED",
            detail="Failed to submit proposal",
        )


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
