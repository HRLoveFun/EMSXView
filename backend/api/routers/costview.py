"""CostView 桥接 router — 将 CostView 服务的 TCA 路由合并进 core 进程（单进程模式）。

背景：CostView 微服务独立运行于 :8002，前端统一走 core :3000 的 /api 入口；
当 core 通过 EMSXVIEW_OPTIONAL_MODULES 加载 costview 时，本模块把
CostView/api/routers 下的路由重新导出并挂载，使 /api/tca/* 与
/api/tca/monitoring/* 在 :3000 上可用，无需额外启动 :8002。

同时承载数据管道 Runner 代理端点（/api/tca/runner/*）——Runner 属独立项目
EMSXDataPipeline（仅本机 :8100 监听），前端统一经 :3000 鉴权入口访问，
不直连 Runner 端口（P2-4 整改）。

import 时执行 CostView 侧必需的 DI 注册（与 CostView/api/main.py 的
_setup_dependencies() 等价，注册函数本身幂等）。
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Depends

from config import settings
from deps import verify_token
from schemas import ApiResponse

logger = logging.getLogger(__name__)


def _setup_costview_dependencies() -> None:
    """注册 CostView 服务依赖（TCA 查询实现 + DataPipeline 配置）。

    经 platform_data 桥接入口完成 DI 注册，避免 backend 直接
    deep import ``CostView.src``（模块边界 AP-01）。
    """
    from platform_data.adapters import register_costview_bridge_dependencies

    register_costview_bridge_dependencies()
    logger.info("DI: CostView dependencies registered (bridge mode)")


_setup_costview_dependencies()

from CostView.api.routers.costview import router as _tca_router  # noqa: E402
from CostView.api.routers.monitoring import router as _monitoring_router  # noqa: E402

#: 合并 CostView 全部路由（既有 /api/tca/* + 监控 /api/tca/monitoring/*）
router = APIRouter()
router.include_router(_tca_router)
router.include_router(_monitoring_router)


# ── 数据管道 Runner 代理（P2-4 整改）────────────────────────────────────────
# Runner 为单任务模型（EMSXDataPipeline 项目），仅提供 POST /run 与 GET /status。


async def _request_runner(method: str, path: str) -> tuple[int, dict | None, str | None]:
    """请求 Runner 并返回 (http_status, json_body, error)。非 2xx 不抛异常。"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, f"{settings.RUNNER_URL}{path}")
    except httpx.HTTPError as exc:
        return 0, None, f"Runner unreachable: {exc}"
    if resp.status_code // 100 != 2:
        # 409（运行中重复触发）由调用方特判，此处按原始状态码透传
        return resp.status_code, None, f"Runner returned HTTP {resp.status_code}"
    try:
        return resp.status_code, resp.json(), None
    except ValueError:
        return resp.status_code, None, "Runner returned non-JSON body"


@router.post("/api/tca/runner/run", response_model=ApiResponse)
async def trigger_pipeline_run(user: dict = Depends(verify_token)) -> ApiResponse:
    """代理 Runner POST /run —— 触发数据管道更新（409 视为已受理）。"""
    status_code, body, error = await _request_runner("POST", "/run")
    if status_code == 409:
        # 运行中重复触发：回带当前任务状态，前端按 running 处理
        _, current, status_error = await _request_runner("GET", "/status")
        if status_error:
            return ApiResponse(success=False, error=status_error, message="pipeline already running")
        return ApiResponse(success=True, data=current, message="pipeline already running")
    if error:
        return ApiResponse(success=False, error=error, message="pipeline trigger failed")
    return ApiResponse(success=True, data=body, message="pipeline triggered")


@router.get("/api/tca/runner/status", response_model=ApiResponse)
async def get_pipeline_run_status(user: dict = Depends(verify_token)) -> ApiResponse:
    """代理 Runner GET /status —— 查询当前数据管道任务状态。"""
    _, body, error = await _request_runner("GET", "/status")
    if error:
        return ApiResponse(success=False, error=error, message="pipeline status unavailable")
    return ApiResponse(success=True, data=body)
