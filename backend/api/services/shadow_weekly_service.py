"""影子周报聚合（057 DL-22/215）。

只读：按 `routing_decisions.created_at` 落在 [start, end] 的记录，按 ISO 周聚合：
覆盖率、一致率、改写率与原因分布、`BLOCK` 硬违例、预期成本（仅在有
`estimated_cost_bps` 时给出建议侧均值，缺失显式披露）。

不把缺失当 0（AT 红线）：分母与 `available` 标志随结果返回。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

logger = logging.getLogger(__name__)

#: 改写原因中表示「未改/不可判定」的值（不计入改写率）
_NOT_REWRITTEN = {"", "UNCLASSIFIED"}


def _parse_day(value: Optional[str], *, end: bool = False) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.strptime(str(value), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if end:
        parsed = parsed.replace(hour=23, minute=59, second=59)
    return parsed


def _iso_week(as_of: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(as_of).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "unknown"
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def _broker_qty(items: list[dict]) -> dict[str, int]:
    return {
        str(item.get("broker") or ""): int(item.get("quantity") or 0)
        for item in items
    }


def _agreed(payload: dict) -> bool:
    actual = _broker_qty(list(payload.get("actual_routes") or []))
    suggested = _broker_qty(list(payload.get("candidates") or []))
    return bool(actual) and actual == suggested


def _empty_bucket() -> dict[str, Any]:
    return {
        "decisions": 0,
        "actual_linked": 0,
        "agreed": 0,
        "rewritten": 0,
        "no_suggestion": 0,
        "hard_violations": 0,
        "by_source": Counter(),
        "reason_counts": Counter(),
        "estimated": [],  # [(quantity, bps)]
    }


def _merge(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in ("decisions", "actual_linked", "agreed", "rewritten",
                "no_suggestion", "hard_violations"):
        target[key] += source[key]
    target["by_source"].update(source["by_source"])
    target["reason_counts"].update(source["reason_counts"])
    target["estimated"].extend(source["estimated"])


def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
    actual = bucket["actual_linked"]
    estimates = bucket["estimated"]
    total_qty = sum(qty for qty, _ in estimates)
    return {
        "decisions": bucket["decisions"],
        "actual_linked": actual,
        "actual_linked_pct": round(actual / bucket["decisions"] * 100.0, 2)
        if bucket["decisions"] else None,
        "agreed": bucket["agreed"],
        "agreement_rate": round(bucket["agreed"] / actual, 4) if actual else None,
        "rewritten": bucket["rewritten"],
        "rewrite_rate": round(bucket["rewritten"] / actual, 4) if actual else None,
        "reason_counts": dict(bucket["reason_counts"]),
        "no_suggestion": bucket["no_suggestion"],
        "hard_violations": bucket["hard_violations"],
        "by_source": dict(bucket["by_source"]),
        "expected_cost": {
            "available": bool(estimates),
            "suggested_mean_bps": (
                round(sum(qty * bps for qty, bps in estimates) / total_qty, 6)
                if total_qty else None
            ),
            "actual_mean_bps": None,
            "note": (
                ""
                if estimates
                else "no estimated_cost_bps on decisions; actual-side estimate not captured"
            ),
        },
    }


async def weekly_report(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """按 ISO 周聚合影子决策；返回 weeks + totals。"""
    from db import get_db_session
    from models.execution_state import RoutingDecisionRecord

    start = _parse_day(start_date)
    end = _parse_day(end_date, end=True)
    stmt = select(RoutingDecisionRecord)
    if start is not None:
        stmt = stmt.where(RoutingDecisionRecord.created_at >= start)
    if end is not None:
        stmt = stmt.where(RoutingDecisionRecord.created_at <= end)
    async with get_db_session() as session:
        result = await session.execute(stmt)
        records = result.scalars().all()

    weeks: dict[str, dict[str, Any]] = {}
    totals = _empty_bucket()
    for record in records:
        payload = record.payload or {}
        week = _iso_week(record.as_of or "")
        bucket = weeks.setdefault(week, _empty_bucket())
        for target in (bucket, totals):
            target["decisions"] += 1
            target["by_source"][record.source or "UNKNOWN"] += 1
            if not payload.get("candidates"):
                target["no_suggestion"] += 1
            for violation in payload.get("constraint_violations") or []:
                if str(violation.get("severity")).upper() == "BLOCK":
                    target["hard_violations"] += 1
            actual_routes = list(payload.get("actual_routes") or [])
            if actual_routes:
                target["actual_linked"] += 1
                reason = str(payload.get("rewrite_reason") or "UNCLASSIFIED")
                target["reason_counts"][reason] += 1
                if reason not in _NOT_REWRITTEN:
                    target["rewritten"] += 1
                if _agreed(payload):
                    target["agreed"] += 1
            for candidate in payload.get("candidates") or []:
                cost = candidate.get("estimated_cost_bps")
                if cost is None:
                    continue
                try:
                    target["estimated"].append(
                        (int(candidate.get("quantity") or 0), float(cost))
                    )
                except (TypeError, ValueError):
                    continue

    return {
        "start_date": start_date,
        "end_date": end_date,
        "weeks": {week: _finalize(bucket) for week, bucket in sorted(weeks.items())},
        "totals": _finalize(totals),
    }
