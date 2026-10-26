"""A03（审计 M1）— 建议单状态回滚测试。

锁死行为：未真正发出 `route_order` 前，检查阶段任何异常/取消都必须把状态
从 `CONFIRMING` 回滚到 `PENDING_CONFIRM`（可重试，不再永久 409），并回填
持久化与审计；走到 `route_order` 后的 504 仍冻结为 `NEEDS_REVIEW`。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import submission_service  # noqa: E402
from services.submission_service import ProposalStatus, submit_proposal_core  # noqa: E402


def _proposal() -> dict:
    return {
        "status": ProposalStatus.PENDING_CONFIRM.value,
        "parent_order_id": "1001",
        "broker": "EQ-AAA",
        "quantity": 100,
        "order_type": "LIMIT",
        "limit_price": 200.0,
        "strategy_params": {},
        "updated_at": "2026-10-26T09:30:00",
    }


def _bloomberg(route_result=None, route_error: Exception | None = None):
    async def _route(_request):
        if route_error is not None:
            raise route_error
        return route_result if route_result is not None else {"routeId": 9001}

    return SimpleNamespace(route_order=_route)


class Recorder:
    """记录 persist_result / audit_result 调用。"""

    def __init__(self):
        self.persisted: list[dict] = []
        self.audited: list[str] = []

    async def persist(self, proposal_id, **kwargs):
        self.persisted.append({"proposal_id": proposal_id, **kwargs})

    def audit(self, correlation_id, result):
        self.audited.append(result)


async def _run(proposal, bloomberg, recorder, *, compliance=None, authorization=None):
    return await submit_proposal_core(
        1,
        proposal,
        bloomberg,
        correlation_id="cid",
        persist_result=recorder.persist,
        audit_result=recorder.audit,
        compliance_check=compliance,
        authorization_check=authorization,
    )


@pytest.mark.asyncio
async def test_compliance_exception_rolls_back():
    """准入检查抛异常（如策略 JSON 损坏）→ 回滚 PENDING_CONFIRM + audit fail。"""
    proposal = _proposal()
    recorder = Recorder()

    async def _boom(_proposal):
        raise ValueError("broken policy json")

    result = await _run(proposal, _bloomberg(), recorder, compliance=_boom)

    assert result.outcome == "FAILED"
    assert proposal["status"] == ProposalStatus.PENDING_CONFIRM.value
    assert recorder.audited == ["fail"]
    assert [item["status"] for item in recorder.persisted] == [ProposalStatus.PENDING_CONFIRM.value]


@pytest.mark.asyncio
async def test_authorization_exception_rolls_back():
    """授权查询抛异常（运营库故障）→ 回滚 PENDING_CONFIRM。"""
    proposal = _proposal()
    recorder = Recorder()

    async def _boom(_proposal):
        raise RuntimeError("db down")

    result = await _run(proposal, _bloomberg(), recorder, authorization=_boom)

    assert result.outcome == "FAILED"
    assert proposal["status"] == ProposalStatus.PENDING_CONFIRM.value
    assert recorder.audited == ["fail"]


@pytest.mark.asyncio
async def test_retry_after_exception_succeeds():
    """回滚后可立即重试（不再 409 already being confirmed）。"""
    proposal = _proposal()
    recorder = Recorder()

    async def _boom(_proposal):
        raise ValueError("broken policy json")

    first = await _run(proposal, _bloomberg(), recorder, compliance=_boom)
    assert first.outcome == "FAILED"

    async def _pass(_proposal):
        return []

    second = await _run(proposal, _bloomberg(), recorder, compliance=_pass)
    assert second.outcome == "SUBMITTED"
    assert proposal["status"] == ProposalStatus.SUBMITTED.value


@pytest.mark.asyncio
async def test_blocked_compliance_returns_and_rolls_back():
    """BLOCK 违规：返回 BLOCKED（不抛），状态回滚。"""
    proposal = _proposal()
    recorder = Recorder()

    async def _block(_proposal):
        return [{"code": "X", "message": "blocked", "severity": "BLOCK"}]

    result = await _run(proposal, _bloomberg(), recorder, compliance=_block)

    assert result.outcome == "BLOCKED"
    assert result.http_status == 400
    assert proposal["status"] == ProposalStatus.PENDING_CONFIRM.value


@pytest.mark.asyncio
async def test_504_after_route_freezes_needs_review():
    """已发出 route_order 后的 504：冻结 NEEDS_REVIEW，不回滚。"""
    proposal = _proposal()
    recorder = Recorder()
    bloomberg = _bloomberg(route_error=HTTPException(504, "timeout"))

    result = await _run(proposal, bloomberg, recorder)

    assert result.outcome == "NEEDS_REVIEW"
    assert proposal["status"] == ProposalStatus.NEEDS_REVIEW.value
    assert recorder.audited == ["unknown"]


@pytest.mark.asyncio
async def test_success_marks_submitted():
    """正常路径：SUBMITTED，持久化带 route_id。"""
    proposal = _proposal()
    recorder = Recorder()

    result = await _run(proposal, _bloomberg({"routeId": 7}), recorder)

    assert result.outcome == "SUBMITTED"
    assert result.route_id == 7
    assert proposal["status"] == ProposalStatus.SUBMITTED.value
    assert recorder.persisted[0]["status"] == ProposalStatus.SUBMITTED.value
    assert recorder.persisted[0]["route_id"] == 7
