"""Orders domain router — /api/orders* and /api/executions* endpoints.

Phase 5: Decomposed into three focused sub-routers:
  - orders_crud.py       — Order CRUD (status, get, modify, route, batch)
  - orders_execution.py  — Parent execution scheduling (create, control, list)
  - orders_handoff.py    — WBS-08 cross-module handoff contracts

This file aggregates all three into a single orders router for backward
compatibility with existing include_router() calls in main.py.
"""

from __future__ import annotations

from fastapi import APIRouter

from .orders_crud import router as crud_router
from .orders_execution import router as execution_router
from .orders_handoff import router as handoff_router

router = APIRouter(tags=["Orders"])

# Aggregate all sub-routers under the main orders router
router.include_router(crud_router)
router.include_router(execution_router)
router.include_router(handoff_router)
