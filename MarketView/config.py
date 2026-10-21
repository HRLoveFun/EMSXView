"""MarketView standalone service configuration."""
from __future__ import annotations

import os

# Handoff backend: "redis" (cross-process) or "memory" (single-process).
# In standalone mode, always "redis" to communicate with the main EMSX service.
os.environ.setdefault("EMSXVIEW_HANDOFF_BACKEND", "redis")
os.environ.setdefault("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

HOST: str = os.getenv("MARKETVIEW_HOST", "0.0.0.0")
PORT: int = int(os.getenv("MARKETVIEW_PORT", "8001"))

# EMSX 订单导出收件箱（057 DL-01）：交易员盘中手工导出的 CSV 落盘目录。
# 目录在仓库外、只增不删（留档）；未配置时盘前单端点返回空数据 + 说明，
# 不设默认值（不同机器导出路径不同，禁止硬编码）。
EXPORT_INBOX_DIR: str = os.getenv("EMSXVIEW_EXPORT_INBOX_DIR", "")
