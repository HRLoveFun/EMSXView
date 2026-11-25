"""影子运行服务（057 DL-22/214，影子方式）。

- 订单/路由事件由订阅引擎回调投递到主循环；
- `on_order`：每个路由订单旁路运行引擎（**只读**，不落 proposal 表），
  跑 A02 `pre_trade_checks`，组装 v2 决策并落库；
- `on_route`：把交易员的实际路由按 `order_id` 关联到最新决策，回填
  `actual_routes / rewrite_reason`；
- 任何失败 **不阻断** 订单/路由主流程（影子语义）。

开关：`EMSXVIEW_SHADOW_RUN_ENABLED`（默认关闭）。无匹配计划时写入
`ENGINE_DEFAULT` 的无建议记录并披露，不臆造计划。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from platform_data.contracts import (
    REWRITE_BROKER_CHANGED,
    REWRITE_EXTRA_ROUTE,
    REWRITE_PARAMS_CHANGED,
    REWRITE_QUANTITY_CHANGED,
    REWRITE_UNCLASSIFIED,
    SOURCE_ENGINE,
    SOURCE_ENGINE_DEFAULT,
)

logger = logging.getLogger(__name__)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float("inf") else None


def route_payload(route: Any) -> dict:
    """Route 模型 → 可序列化的实际路由摘要（不含行情/富化字段）。"""
    route_id = getattr(route, "routeId", None) or getattr(route, "route_id", None)
    sequence = getattr(route, "sequence", None)
    return {
        "route_id": str(route_id or ""),
        "order_id": str(sequence or getattr(route, "parent_order_id", "") or ""),
        "broker": str(getattr(route, "broker", "") or ""),
        "quantity": int(getattr(route, "quantity", 0) or 0),
        "strategy_type": str(getattr(route, "strategyType", "") or ""),
        "status": str(getattr(route, "status", "") or ""),
        "filled_quantity": int(getattr(route, "filledQuantity", 0) or 0),
        "limit_price": _finite(getattr(route, "limitPrice", None)),
    }


def rewrite_reason(candidates: list[dict], actual_routes: list[dict]) -> str:
    """实际 vs 建议的事后归类（不臆造交易员主观原因）。"""
    if not candidates:
        return REWRITE_UNCLASSIFIED
    suggested = {str(item.get("broker") or "") for item in candidates}
    actual = {str(item.get("broker") or "") for item in actual_routes}
    # 完全换券商（A→B）归 BROKER_CHANGED；在建议之外再加路由归 EXTRA_ROUTE
    if actual and suggested and not (actual & suggested):
        return REWRITE_BROKER_CHANGED
    if actual - suggested:
        return REWRITE_EXTRA_ROUTE
    if suggested - actual:
        return REWRITE_BROKER_CHANGED

    suggested_by_broker = {
        str(item.get("broker") or ""): int(item.get("quantity") or 0) for item in candidates
    }
    actual_by_broker = {
        str(item.get("broker") or ""): int(item.get("quantity") or 0) for item in actual_routes
    }
    if suggested_by_broker != actual_by_broker:
        return REWRITE_QUANTITY_CHANGED

    suggested_params = {
        str(item.get("broker") or ""): item.get("strategy_params") or {} for item in candidates
    }
    for item in actual_routes:
        broker = str(item.get("broker") or "")
        expected = suggested_params.get(broker) or {}
        actual_strategy = str(item.get("strategy_type") or "").upper()
        expected_strategy = str(
            expected.get("strategy_type") or expected.get("StrategyType") or ""
        ).upper()
        if expected_strategy and actual_strategy and expected_strategy != actual_strategy:
            return REWRITE_PARAMS_CHANGED
        actual_limit = _finite(item.get("limit_price"))
        expected_limit = _finite(expected.get("limit_price"))
        if (
            expected_limit is not None
            and actual_limit is not None
            and abs(expected_limit - actual_limit) > 1e-9
        ):
            return REWRITE_PARAMS_CHANGED
    return REWRITE_UNCLASSIFIED


async def quote_spread_bps(bloomberg: Any, symbol: str) -> float | None:
    """决策时点报价价差（bps）；不可得返回 None（不以 0 填充）。"""
    if bloomberg is None or not symbol:
        return None
    getter = getattr(bloomberg, "get_quote", None)
    if not callable(getter):
        return None
    try:
        quote = getter(symbol)
        if asyncio.iscoroutine(quote):
            quote = await quote
    except Exception:  # 行情不可得不是决策失败
        return None
    if quote is None:
        return None
    if isinstance(quote, dict):
        bid, ask = _finite(quote.get("bid")), _finite(quote.get("ask"))
    else:
        bid, ask = _finite(getattr(quote, "bid", None)), _finite(getattr(quote, "ask", None))
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = (bid + ask) / 2.0
    return round((ask - bid) / mid * 10_000.0, 4) if mid > 0 else None


def _order_version(order: Any) -> str:
    return "|".join(
        str(value)
        for value in (
            getattr(order, "id", ""),
            getattr(order, "symbol", ""),
            getattr(order, "side", ""),
            getattr(order, "status", ""),
            getattr(order, "remainingQuantity", ""),
            getattr(order, "price", ""),
        )
    )


class ShadowRunner:
    """影子运行器（单例；engine/bloomberg 由 main lifespan 注入）。"""

    def __init__(self, engine: Any = None, bloomberg: Any = None) -> None:
        self.engine = engine
        self.bloomberg = bloomberg
        self._seen_versions: dict[str, str] = {}
        self._actual_routes: dict[str, list[dict]] = {}
        self._latest_payloads: dict[str, dict] = {}

    def configure(self, engine: Any, bloomberg: Any = None) -> None:
        self.engine = engine
        self.bloomberg = bloomberg

    async def on_order(self, order: Any) -> None:
        """订单事件：旁路生成建议、约束检查、记录决策（失败不阻断）。"""
        try:
            from services.decision_log_service import (
                build_shadow_decision,
                record_decision,
                shadow_run_enabled,
            )
            from services.pre_trade_checks import pre_trade_checks

            if not shadow_run_enabled() or self.engine is None:
                return
            order_id = str(getattr(order, "id", "") or "")
            version = _order_version(order)
            if self._seen_versions.get(order_id) == version:
                return

            plans = await self.engine.repo.list_active_auto_plans()
            matched = self.engine.match_plans(order, plans) if plans else []
            plan = matched[0] if matched else None
            spread = await quote_spread_bps(self.bloomberg, str(getattr(order, "symbol", "") or ""))
            market_state = {
                "symbol": str(getattr(order, "symbol", "") or ""),
                "side": str(getattr(order, "side", "") or ""),
                "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }

            if plan is None:
                decision = build_shadow_decision(
                    order,
                    SimpleNamespace(id=None, split_type="", participation_rate=None),
                    [],
                    context={
                        "source": SOURCE_ENGINE_DEFAULT,
                        "rationale": "no_matching_plan",
                        "quote_spread_bps": spread,
                        "market_state": market_state,
                        "intent_source": "unknown",
                    },
                )
            else:
                proposals = await self.engine.generate_proposals(
                    order, plan, record_shadow=False
                )
                violations: list[dict] = []
                for proposal in proposals:
                    try:
                        found = await pre_trade_checks(order, proposal, self.bloomberg)
                    except Exception:  # 约束检查异常不阻断决策写入
                        logger.warning("shadow pre-trade check failed", exc_info=True)
                        found = []
                    violations.extend(found)
                decision = build_shadow_decision(
                    order,
                    plan,
                    proposals,
                    context={
                        "source": SOURCE_ENGINE,
                        "quote_spread_bps": spread,
                        "market_state": market_state,
                        "constraint_violations": violations,
                        "intent_source": "unknown",
                    },
                )

            recorded = await record_decision(decision)
            if recorded:
                self._seen_versions[order_id] = version
                self._latest_payloads[order_id] = {
                    "candidates": [
                        {"broker": candidate.broker, "quantity": candidate.quantity,
                         "strategy_params": dict(candidate.strategy_params)}
                        for candidate in decision.candidates
                    ],
                }
        except Exception:  # 影子运行绝不阻断订单主流程
            logger.warning("shadow on_order failed", exc_info=True)

    async def on_route(self, route: Any) -> None:
        """路由事件：按 order_id 关联实际路由并回填（）。"""
        try:
            from services.decision_log_service import (
                load_decisions,
                shadow_run_enabled,
                update_actual_routes,
            )

            if not shadow_run_enabled():
                return
            payload = route_payload(route)
            order_id = payload["order_id"]
            if not order_id:
                return
            route_id = payload["route_id"]
            items = self._actual_routes.setdefault(order_id, [])
            replaced = False
            for index, item in enumerate(items):
                if route_id and item.get("route_id") == route_id:
                    items[index] = payload
                    replaced = True
                    break
            if not replaced:
                items.append(payload)

            decision_payload = self._latest_payloads.get(order_id)
            if decision_payload is None:
                records = await load_decisions(order_id=order_id, limit=1)
                decision_payload = (records[0].get("payload") if records else None) or {}
                self._latest_payloads[order_id] = decision_payload
            reason = rewrite_reason(
                list(decision_payload.get("candidates") or []), items
            )
            await update_actual_routes(order_id, list(items), reason)
            decision_payload["actual_routes"] = list(items)
            decision_payload["rewrite_reason"] = reason
        except Exception:  # 影子关联绝不阻断路由主流程
            logger.warning("shadow on_route failed", exc_info=True)


_runner = ShadowRunner()


def get_shadow_runner() -> ShadowRunner:
    """进程内影子运行器单例（订阅引擎回调注册用）。"""
    return _runner


def configure_shadow_runner(engine: Any, bloomberg: Any = None) -> ShadowRunner:
    """main lifespan 注入引擎与 Bloomberg facade。"""
    _runner.configure(engine, bloomberg)
    return _runner
