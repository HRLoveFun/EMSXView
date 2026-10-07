"""PM 授权剩余量计算服务 (S12/042)。

剩余授权 = target_quantity − 执行占用。
执行占用 = Σ(该 symbol+side(+portfolio) 维度下 ACTIVE/PAUSED 父单的
target_quantity)——父单创建即占用授权（含计划中未提交的切片），
与报告场景「其中 30 万股正在券商算法中执行，系统应知道剩余授权」一致。

父单没有 symbol/portfolio 列（历史表结构），经 orders_projection 的
payload（订阅 write-through，见 S4）按 order_id 关联补齐维度。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _match(intent: Dict[str, Any], symbol: str, side: str, portfolio: Optional[str]) -> bool:
    """授权维度匹配：symbol/side 精确；intent 的 portfolio 为空 = 不限组合。"""
    return (
        intent.get("symbol", "").upper() == symbol.upper()
        and intent.get("side", "").upper() == side.upper()
        and (not intent.get("portfolio") or intent["portfolio"] == (portfolio or ""))
    )


def compute_remaining(
    intents: List[Dict[str, Any]],
    parents: List[Any],
    order_payloads: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """计算各授权的剩余量。

    intents：provider.load_authorizations() 形态；
    parents：ACTIVE/PAUSED 父单（run_parent_child_op("list_active_parents")），
             以 id 为键去重；
    order_payloads：order_id → {symbol, side, portfolio}（orders_projection payload）。
    返回按 intent 展开的剩余量视图。
    """
    # 父单占用聚合：(symbol, side, portfolio) → Σ target_quantity
    committed_by_key: Dict[tuple, Dict[str, Any]] = {}
    for p in parents:
        payload = order_payloads.get(str(getattr(p, "order_id", ""))) or {}
        symbol = payload.get("symbol", "")
        if not symbol:
            # 订单投影缺失——占用无法归属，记警不中断其余聚合
            logger.warning(
                "Parent %s order payload missing — excluded from authorization commit",
                getattr(p, "id", "?"),
            )
            continue
        key = (
            symbol,
            payload.get("side", ""),
            payload.get("portfolio", ""),
        )
        entry = committed_by_key.setdefault(key, {"committed": 0, "filled": 0, "parents": 0})
        entry["committed"] += int(getattr(p, "target_quantity", 0) or 0)
        entry["filled"] += int(getattr(p, "filled_quantity", 0) or 0)
        entry["parents"] += 1

    views: List[Dict[str, Any]] = []
    for intent in intents:
        target = int(intent.get("target_quantity", 0) or 0)
        symbol = intent.get("symbol", "")
        side = intent.get("side", "")
        portfolio = intent.get("portfolio")

        # 该授权覆盖的占用 = 精确匹配键 + portfolio 不限（空）时合并同 symbol+side
        committed = 0
        filled = 0
        for (k_sym, k_side, k_pf), agg in committed_by_key.items():
            if k_sym.upper() != symbol.upper() or k_side.upper() != side.upper():
                continue
            if portfolio and k_pf != portfolio:
                continue
            committed += agg["committed"]
            filled += agg["filled"]

        views.append({
            "id": intent.get("id"),
            "symbol": symbol,
            "side": side,
            "portfolio": portfolio,
            "targetQuantity": target,
            "committedQuantity": committed,
            "filledQuantity": filled,
            "remainingQuantity": max(0, target - committed),
            "note": intent.get("note"),
            "updatedAt": intent.get("updated_at", ""),
        })
    return views


def check_authorization(
    intents: List[Dict[str, Any]],
    parents: List[Any],
    order_payloads: Dict[str, Dict[str, Any]],
    *,
    symbol: str,
    side: str,
    portfolio: Optional[str],
    additional_qty: int,
) -> Dict[str, Any]:
    """下单入口授权检查 (S12/042)。

    返回 {"outcome": "not_covered" | "exceeded" | "ok", ...}：
    - not_covered：无匹配授权——调用方按部署策略决定放行（warn）或拒绝；
    - exceeded：剩余授权不足——硬拒绝；
    - ok：在授权范围内。
    """
    covered = [i for i in intents if _match(i, symbol, side, portfolio)]
    if not covered:
        return {"outcome": "not_covered", "symbol": symbol, "side": side}

    views = compute_remaining(covered, parents, order_payloads)
    best = max(views, key=lambda v: v["remainingQuantity"])
    if additional_qty > best["remainingQuantity"]:
        return {
            "outcome": "exceeded",
            "symbol": symbol,
            "side": side,
            "requested": additional_qty,
            "remainingQuantity": best["remainingQuantity"],
            "authorizationId": best["id"],
        }
    return {
        "outcome": "ok",
        "symbol": symbol,
        "side": side,
        "remainingQuantity": best["remainingQuantity"],
        "authorizationId": best["id"],
    }


async def enforce_for_order(
    provider,
    *,
    symbol: str,
    side: str,
    portfolio: Optional[str],
    additional_qty: int,
) -> Optional[Dict[str, Any]]:
    """下单入口授权检查的 async 包装 (S13/043)。

    返回：
    - None：持久化不可用（纯内存模式）——检查跳过；
    - not_covered：无匹配授权——调用方放行并告警（未登记授权不阻断，
      严格模式由部署策略决定，见 plan.md）；
    - exceeded：剩余授权不足——调用方硬拒绝（403）；
    - ok：放行。
    """
    if not (provider and provider.is_active):
        return None
    intents = await provider.load_authorizations(active_only=True)
    if not intents:
        return {"outcome": "not_covered", "symbol": symbol, "side": side}
    parents = await provider.run_parent_child_op("list_active_parents") or []
    payloads: Dict[str, Dict[str, Any]] = {}
    for p in await provider.load_orders(limit=5000):
        oid = str(p.get("id") or p.get("orderId") or "")
        if oid:
            payloads[oid] = p
    return check_authorization(
        intents, parents, payloads,
        symbol=symbol, side=side, portfolio=portfolio,
        additional_qty=additional_qty,
    )
