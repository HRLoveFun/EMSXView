#!/usr/bin/env python3
"""MarketView — standalone FastAPI service on port 8001.

Does NOT depend on Bloomberg EMSX session. Communicates with the main
EMSXView service via Redis handoff exchange (cross-process mode).

Run:
    python main.py
    uvicorn main:app --host 127.0.0.1 --port 8001
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Apply config before importing platform_data (sets EMSXVIEW_HANDOFF_BACKEND=redis)
import config  # noqa: F401

from routers.marketview import router as marketview_router
from routers.export_orders import router as export_orders_router
from routers.baseline import router as baseline_router
from routers.regime import router as regime_router
from routers.pretrade import router as pretrade_router
from routers.pool_board import router as pool_board_router  # 057 DL-29
from routers.monitor_board import router as monitor_board_router  # 057 节点一监控台

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EMSXView — Market View",
    description="Pre-trade market snapshot and candidate handoff service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    # A04（M2）：显式来源白名单 + 关闭 credentials（不再使用 "*" 组合）
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(marketview_router)
app.include_router(export_orders_router)
app.include_router(baseline_router)
app.include_router(regime_router)
app.include_router(pretrade_router)
app.include_router(pool_board_router)
app.include_router(monitor_board_router)

logger.info("MarketView service ready — listening on port %s", config.PORT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, log_level="info")
