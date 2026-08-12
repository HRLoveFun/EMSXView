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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _setup_dependencies() -> None:
    """Initialize all dependency injection registrations.

    通过 platform_data 桥接入口完成 CostView 分析层依赖注册（TCA 查询
    实现 + DataPipeline 配置），与 core 单进程 merge 模式共用同一逻辑。
    """
    from platform_data.adapters import register_costview_bridge_dependencies

    register_costview_bridge_dependencies()


# Must run BEFORE importing routers that consume platform_data
_setup_dependencies()

from routers.costview import router as costview_router
from routers.monitoring import router as monitoring_router

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
app.include_router(monitoring_router)

logger.info("CostView service ready — listening on port %s", config.PORT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, log_level="info")
