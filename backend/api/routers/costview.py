"""CostView 桥接 router — 将 CostView 服务的 TCA 路由合并进 core 进程（单进程模式）。

背景：CostView 微服务独立运行于 :8002，前端统一走 core :3000 的 /api 入口；
当 core 通过 EMSXVIEW_OPTIONAL_MODULES 加载 costview 时，本模块把
CostView/api/routers 下的路由重新导出并挂载，使 /api/tca/* 与
/api/tca/monitoring/* 在 :3000 上可用，无需额外启动 :8002。

import 时执行 CostView 侧必需的 DI 注册（与 CostView/api/main.py 的
_setup_dependencies() 等价，注册函数本身幂等）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

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
