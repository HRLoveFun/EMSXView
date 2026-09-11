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
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Apply config before importing platform_data (sets EMSXVIEW_HANDOFF_BACKEND=redis)
import config  # noqa: F401

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动自检（P3 整改）：显式暴露运行模式与 handoff 后端一致性。

    独立进程（本文件）必须跨进程交换 handoff 数据；若被显式改回
    memory 后端，recommendations 将对本进程外的消费方不可见，
    启动即告警而不是静默失效。
    """
    backend = os.getenv("EMSXVIEW_HANDOFF_BACKEND", "memory")
    logger.info(
        "CostView 运行模式=standalone (port %s) handoff_backend=%s",
        config.PORT, backend,
    )
    if backend != "redis":
        logger.warning(
            "standalone 模式 + handoff_backend=%s：recommendations 仅本进程可见，"
            "其他进程（core/ExecutionView）读不到；跨进程部署请设置 "
            "EMSXVIEW_HANDOFF_BACKEND=redis", backend,
        )
    yield
    logger.info("CostView 服务关闭")


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
    lifespan=lifespan,
)

# P2-1 整改：关闭 allow_credentials —— 通配符 origin + credentials 组合违反
# CORS 规范（Starlette 会回显任意 Origin），等于放开全站带凭证跨域。
# 本服务经 Authorization 头携带 token（由 JS 显式设置，不受 credentials 语义影响），
# 关闭后前端不受影响；恶意网页也无法再借凭证语义跨域调用。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(costview_router)
app.include_router(monitoring_router)

logger.info("CostView service ready — listening on port %s", config.PORT)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=config.HOST, port=config.PORT, log_level="info")
