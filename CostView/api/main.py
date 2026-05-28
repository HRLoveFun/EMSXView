#!/usr/bin/env python3
"""CostView — standalone FastAPI service on port 8002.

Does NOT depend on Bloomberg EMSX session. Communicates with the main
EMSXView service via Redis handoff exchange (cross-process mode).

Run:
    python main.py
    uvicorn main:app --host 0.0.0.0 --port 8002
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Apply config before importing platform_data (sets EMSXVIEW_HANDOFF_BACKEND=redis)
import config  # noqa: F401

from routers.costview import router as costview_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="EMSXView — Cost View",
    description="Post-trade TCA analytics and broker recommendation service",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(costview_router)

logger.info("CostView service ready — listening on port %s", config.PORT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, log_level="info")
