"""Route Engine — matches incoming orders against route plans and generates sub-order proposals.

Core responsibilities:
  1. Match orders to route plans by symbol/side/portfolio/trader/exchange criteria
  2. Generate sub-order proposals based on plan split strategy (broker/time/hybrid)
  3. Validate quantity constraints and distribute with largest-remainder rounding
"""

from __future__ import annotations

import fnmatch
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from models.route_plan import (
    AllocationType,
    RoutePlan,
    RoutePlanAllocation,
    SplitType,
)
from schemas import Order

logger = logging.getLogger(__name__)


class RouteEngine:
    """Matches orders to route plans and generates sub-order proposals.

    The *repo* argument is any object that provides:
      - get_plan(plan_id) -> dict|None
      - list_active_auto_plans() -> list[dict]
      - get_allocations_for_plan(plan_id) -> list[dict]
      - delete_proposals_for_order(parent_order_id) -> None
      - create_proposals_bulk(proposals: list[dict]) -> list[dict]
    """

    def __init__(self, repo: Any):
        self.repo = repo

    # ------------------------------------------------------------------
    # Matching
    # ------------------------------------------------------------------

    def match_plans(self, order: Order, plans: list[RoutePlan]) -> list[RoutePlan]:
        """Return plans that match the given order, sorted by priority (highest first).

        Matching rules:
          - match_symbol uses fnmatch (supports * and ? wildcards); NULL matches all
          - match_side: BOTH matches everything, BUY/SELL exact match
          - match_portfolio / match_trader / match_exchange: case-insensitive substring
            (order value contains the plan pattern); NULL matches all
        """
        matched: list[tuple[int, RoutePlan]] = []  # (priority, plan)

        for plan in plans:
            if not self._order_matches_plan(order, plan):
                continue
            matched.append((plan.priority, plan))

        # Sort by priority descending, then by created_at descending for ties
        matched.sort(key=lambda x: (-x[0], -(x[1].created_at.timestamp() if x[1].created_at else 0)))
        return [plan for _, plan in matched]

    def _order_matches_plan(self, order: Order, plan: RoutePlan) -> bool:
        """Check if a single order matches a single plan's criteria."""
        # Market: REQUIRED — plan always has market, must match order's exchange
        plan_market = (getattr(plan, "match_market", "") or "").strip().upper()
        if plan_market:
            order_exchange = (order.exchange or "").strip().upper()
            if order_exchange != plan_market:
                return False

        # Symbol: fnmatch with wildcard support
        if plan.match_symbol and plan.match_symbol.strip():
            pattern = plan.match_symbol.strip().upper()
            symbol = (order.symbol or "").upper()
            if not fnmatch.fnmatch(symbol, pattern):
                return False

        # Side
        if plan.match_side and plan.match_side != "BOTH":
            if (order.side or "").upper() != plan.match_side.upper():
                return False

        # Portfolio
        if plan.match_portfolio and plan.match_portfolio.strip():
            pattern = plan.match_portfolio.strip().upper()
            portfolio = (order.portfolio or "").upper()
            if pattern not in portfolio:
                return False

        # Trader
        if plan.match_trader and plan.match_trader.strip():
            pattern = plan.match_trader.strip().upper()
            trader = (order.trader or "").upper()
            if pattern not in trader:
                return False

        # Exchange
        if plan.match_exchange and plan.match_exchange.strip():
            pattern = plan.match_exchange.strip().upper()
            exchange = (order.exchange or "").upper()
            if pattern not in exchange:
                return False

        # Currency: optional exact match
        if plan.match_currency and plan.match_currency.strip():
            plan_ccy = plan.match_currency.strip().upper()
            order_ccy = (order.currency or "").strip().upper()
            if plan_ccy != order_ccy:
                return False

        return True

    # ------------------------------------------------------------------
    # Proposal generation
    # ------------------------------------------------------------------

    async def generate_proposals(
        self, order: Order, plan: RoutePlan
    ) -> list[dict]:
        """Generate sub-order proposal dicts from an order and plan.

        Delegates to the appropriate strategy based on plan.split_type.
        """
        # Load allocations if needed
        allocations: list[RoutePlanAllocation] = []
        if plan.split_type in (SplitType.BROKER_SPLIT.value, SplitType.HYBRID.value):
            allocations = await self.repo.get_allocations_for_plan(plan.id)

        if plan.split_type == SplitType.BROKER_SPLIT.value:
            return self._generate_broker_split(order, plan, allocations)
        elif plan.split_type == SplitType.TIME_SCHEDULE.value:
            return self._generate_time_schedule(order, plan)
        elif plan.split_type == SplitType.HYBRID.value:
            return self._generate_hybrid(order, plan, allocations)
        else:
            logger.warning("Unknown split_type '%s' for plan %d", plan.split_type, plan.id)
            return []

    def _generate_broker_split(
        self, order: Order, plan: RoutePlan, allocations: list[RoutePlanAllocation]
    ) -> list[dict]:
        """Generate proposals by splitting the order across brokers."""
        if not allocations:
            logger.warning("Plan %d has BROKER_SPLIT but no allocations", plan.id)
            return []

        total_qty = order.remainingQuantity
        if total_qty <= 0:
            return []

        # Separate percentage and fixed allocations
        pct_allocations = [a for a in allocations if a.allocation_type == AllocationType.PERCENTAGE.value]
        fixed_allocations = [a for a in allocations if a.allocation_type == AllocationType.FIXED.value]

        # Sum fixed quantities
        fixed_total = int(sum(a.allocation_value for a in fixed_allocations))
        if fixed_total > total_qty:
            logger.warning(
                "Plan %d fixed allocations (%d) exceed order remaining (%d)",
                plan.id, fixed_total, total_qty,
            )
            fixed_total = total_qty

        remaining_qty = total_qty - fixed_total

        # Distribute remaining by percentage using largest-remainder
        pct_quantities = self._distribute_by_percentage(remaining_qty, pct_allocations)

        proposals: list[dict] = []
        # Fixed allocations
        for alloc in fixed_allocations:
            qty = int(alloc.allocation_value)
            if qty <= 0:
                continue
            props = self._build_proposal_base(order, plan, alloc, qty)
            proposals.append(props)

        # Percentage allocations
        for alloc, qty in zip(pct_allocations, pct_quantities):
            if qty <= 0:
                continue
            props = self._build_proposal_base(order, plan, alloc, qty)
            proposals.append(props)

        return proposals

    @staticmethod
    def _distribute_by_percentage(
        total: int, allocations: list[RoutePlanAllocation]
    ) -> list[int]:
        """Distribute total quantity by percentage values using largest-remainder rounding."""
        if total <= 0:
            return [0] * len(allocations)

        pcts = [a.allocation_value for a in allocations]
        total_pct = sum(pcts)
        if total_pct <= 0:
            return [0] * len(allocations)

        raw = [total * (p / total_pct) for p in pcts]
        floored = [int(r) for r in raw]
        remainders = [r - f for r, f in zip(raw, floored)]
        shortfall = total - sum(floored)

        # Allocate extra units to buckets with largest fractional remainders
        indices = sorted(range(len(remainders)), key=lambda i: remainders[i], reverse=True)
        for i in range(shortfall):
            floored[indices[i]] += 1

        return floored

    def _generate_time_schedule(self, order: Order, plan: RoutePlan) -> list[dict]:
        """Generate time-based slices using the benchmark engine.

        Falls back to uniform distribution if benchmark_engine is unavailable.
        """
        if not plan.schedule_type or not plan.num_slices or plan.num_slices <= 0:
            logger.warning("Plan %d has TIME_SCHEDULE but missing schedule_type or num_slices", plan.id)
            return []

        total_qty = order.remainingQuantity
        if total_qty <= 0:
            return []

        # Determine time window
        now = datetime.now(timezone.utc)
        start = now + timedelta(minutes=plan.default_start_offset_min or 5)
        end = self._parse_end_time(plan.default_end_time_local, now)

        if end <= start:
            logger.warning("Plan %d end time %s <= start %s", plan.id, end, start)
            end = start + timedelta(hours=1)

        try:
            from services.benchmark_engine import (
                ScheduleRequest,
                VolumeProfile,
                compute_schedule,
            )
            from models.parent_child_orders import ScheduleType

            st = ScheduleType(plan.schedule_type)
            vp = VolumeProfile(buckets=[1.0] * plan.num_slices)  # uniform profile fallback

            req = ScheduleRequest(
                schedule_type=st,
                target_quantity=total_qty,
                start_time=start,
                end_time=end,
                num_slices=plan.num_slices,
                participation_rate=plan.participation_rate,
                volume_profile=vp,
            )
            slices = compute_schedule(req)

            broker = plan.default_broker or order.broker or ""
            order_type = plan.default_order_type or order.orderType
            tif = plan.default_tif or order.timeInForce

            return [
                {
                    "broker": broker,
                    "quantity": s.planned_quantity,
                    "order_type": order_type,
                    "limit_price": order.price,
                    "tif": tif,
                    "strategy_params": plan.default_strategy_params,
                    "slice_index": s.slice_index,
                    "scheduled_start": s.scheduled_start.isoformat(),
                    "scheduled_end": s.scheduled_end.isoformat(),
                }
                for s in slices
            ]
        except ImportError:
            logger.warning("benchmark_engine not available, using uniform time split")
            return self._uniform_time_split(order, plan, start, end)

    def _generate_hybrid(
        self, order: Order, plan: RoutePlan, allocations: list[RoutePlanAllocation]
    ) -> list[dict]:
        """First split by broker, then apply time schedule within each broker allocation."""
        # Step 1: Broker split
        broker_proposals = self._generate_broker_split(order, plan, allocations)

        if not broker_proposals or not plan.num_slices or plan.num_slices <= 1:
            return broker_proposals

        # Step 2: Time-split each broker allocation
        now = datetime.now(timezone.utc)
        start = now + timedelta(minutes=plan.default_start_offset_min or 5)
        end = self._parse_end_time(plan.default_end_time_local, now)

        if end <= start:
            end = start + timedelta(hours=1)

        try:
            from services.benchmark_engine import (
                ScheduleRequest,
                VolumeProfile,
                compute_schedule,
            )
            from models.parent_child_orders import ScheduleType

            st = ScheduleType(plan.schedule_type or "TWAP")
            vp = VolumeProfile(buckets=[1.0] * plan.num_slices)

            result: list[dict] = []
            for bp in broker_proposals:
                if bp["quantity"] <= 0:
                    continue
                req = ScheduleRequest(
                    schedule_type=st,
                    target_quantity=bp["quantity"],
                    start_time=start,
                    end_time=end,
                    num_slices=plan.num_slices,
                    participation_rate=plan.participation_rate,
                    volume_profile=vp,
                )
                slices = compute_schedule(req)
                for s in slices:
                    result.append({
                        **bp,
                        "quantity": s.planned_quantity,
                        "slice_index": s.slice_index,
                        "scheduled_start": s.scheduled_start.isoformat(),
                        "scheduled_end": s.scheduled_end.isoformat(),
                    })
            return result
        except ImportError:
            return broker_proposals

    # ------------------------------------------------------------------
    # All-in-one processing
    # ------------------------------------------------------------------

    async def process_order(
        self,
        order: Order,
        *,
        plan_id: int | None = None,
    ) -> list[dict]:
        """Process a single order through the RouteEngine.

        If plan_id is given, use that specific plan (MANUAL mode).
        Otherwise, auto-match against enabled AUTO-mode plans.

        Returns list of proposal dicts that were persisted.
        """
        if plan_id is not None:
            plan = await self.repo.get_plan(plan_id)
            if plan is None:
                logger.warning("Plan %d not found", plan_id)
                return []
            plans = [plan]
        else:
            plans = await self.repo.list_active_auto_plans()
            if not plans:
                return []
            plans = self.match_plans(order, plans)

        if not plans:
            return []

        # Use the highest-priority matching plan
        best_plan = plans[0]
        logger.info(
            "RouteEngine processing order %s (%s) with plan '%s' (id=%d)",
            order.id, order.symbol, best_plan.name, best_plan.id,
        )

        # Clear existing pending proposals for this order
        await self.repo.delete_proposals_for_order(order.id)

        # Generate proposals
        proposal_dicts = await self.generate_proposals(order, best_plan)

        if not proposal_dicts:
            logger.info("No proposals generated for order %s with plan %d", order.id, best_plan.id)
            return []

        # Enrich with parent order snapshot
        for pd in proposal_dicts:
            pd["route_plan_id"] = best_plan.id
            pd["parent_order_id"] = order.id
            pd["parent_symbol"] = order.symbol
            pd["parent_side"] = (order.side or "") if hasattr(order, 'side') else ""
            pd["parent_trader"] = order.trader
            pd["parent_portfolio"] = order.portfolio or ""
            pd["status"] = "PENDING_CONFIRM"

        # Persist
        persisted = await self.repo.create_proposals_bulk(proposal_dicts)
        logger.warning(
            "RouteEngine created %d proposals for order %s via plan '%s'",
            len(persisted), order.id, best_plan.name,
        )

        return proposal_dicts

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_proposal_base(
        order: Order,
        plan: RoutePlan,
        alloc: RoutePlanAllocation,
        quantity: int,
    ) -> dict:
        """Build a base proposal dict from plan/order/allocation defaults."""
        return {
            "broker": alloc.broker,
            "quantity": quantity,
            "order_type": alloc.order_type or plan.default_order_type or order.orderType,
            "limit_price": order.price,
            "tif": plan.default_tif or order.timeInForce,
            "strategy_params": alloc.strategy_params or plan.default_strategy_params,
        }

    @staticmethod
    def _parse_end_time(time_str: str | None, now: datetime) -> datetime:
        """Parse a local time string like '16:00' into a UTC datetime."""
        if not time_str:
            return now + timedelta(hours=6)
        try:
            parts = time_str.strip().split(":")
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            # Use naive local time and assume UTC for simplicity
            end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if end <= now:
                end += timedelta(days=1)
            return end
        except (ValueError, IndexError):
            return now + timedelta(hours=6)

    @staticmethod
    def _uniform_time_split(
        order: Order,
        plan: RoutePlan,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Simple uniform time split when benchmark_engine is unavailable."""
        n = plan.num_slices or 1
        if n <= 0:
            n = 1
        total_qty = order.remainingQuantity
        if total_qty <= 0:
            return []

        # Distribute quantity evenly with largest-remainder
        base = total_qty // n
        remainder = total_qty % n
        total_secs = (end - start).total_seconds()
        bucket_secs = total_secs / n

        broker = plan.default_broker or order.broker or ""
        order_type = plan.default_order_type or order.orderType
        tif = plan.default_tif or order.timeInForce

        proposals: list[dict] = []
        for i in range(n):
            qty = base + (1 if i < remainder else 0)
            if qty <= 0:
                continue
            s_start = start + timedelta(seconds=bucket_secs * i)
            s_end = start + timedelta(seconds=bucket_secs * (i + 1))
            proposals.append({
                "broker": broker,
                "quantity": qty,
                "order_type": order_type,
                "limit_price": order.price,
                "tif": tif,
                "strategy_params": plan.default_strategy_params,
                "slice_index": i,
                "scheduled_start": s_start.isoformat(),
                "scheduled_end": s_end.isoformat(),
            })
        return proposals
