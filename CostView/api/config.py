"""CostView standalone service configuration."""
from __future__ import annotations

import os

# Handoff backend: "redis" (cross-process) or "memory" (single-process).
os.environ.setdefault("EMSXVIEW_HANDOFF_BACKEND", "redis")
os.environ.setdefault("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

# P1-3 整改：默认仅绑定回环地址——服务无鉴权且含写端点（recommendations/pin），
# 暴露面收敛为 nginx 同机反代（README 拓扑）。需跨机直连时显式设置
# COSTVIEW_HOST=0.0.0.0 并自行承担网络边界控制（防火墙/反代鉴权）。
HOST: str = os.getenv("COSTVIEW_HOST", "127.0.0.1")
PORT: int = int(os.getenv("COSTVIEW_PORT", "8002"))

# 数据目录统一从 DataPipeline.config 派生（ADR-0012 单一来源 + 009-external-data-store
# 默认外置到 ~/EMSXViewData/data；EMSXVIEW_DATA_DIR 环境变量覆盖在 Config 内生效）。
# 此前本文件自行计算 CostView/data 默认值，属双真相源残留，已收敛。
from data_access.config import Config as _PipelineConfig  # noqa: E402

DATA_DIR: str = str(_PipelineConfig.DATA_DIR)
