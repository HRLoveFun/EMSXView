"""MarketView standalone service configuration."""
from __future__ import annotations

import os
from pathlib import Path

# 与 core backend 对齐：读取仓库根 .env（本地文件、已 gitignore）。
# 无 python-dotenv 或文件不存在时静默跳过，不改变原有「只认进程环境变量」的行为。
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass


# Handoff backend: "redis" (cross-process) or "memory" (single-process).
# In standalone mode, always "redis" to communicate with the main EMSX service.
os.environ.setdefault("EMSXVIEW_HANDOFF_BACKEND", "redis")
os.environ.setdefault("EMSXVIEW_REDIS_URL", "redis://localhost:6379/0")

# A04（M2）：默认只监听回环地址（与 CostView 一致），需要对外暴露时显式覆盖。
HOST: str = os.getenv("MARKETVIEW_HOST", "127.0.0.1")
PORT: int = int(os.getenv("MARKETVIEW_PORT", "8001"))

# A04（M2）：handoff 写端点 JWT 校验，与 core backend 共用同一 secret / 算法。
JWT_SECRET: str = os.getenv("JWT_SECRET", "")
JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")

# A04（M2）：CORS 白名单（逗号分隔）；不再使用 "*" + credentials 组合。
ALLOWED_ORIGINS: list[str] = [
    origin.strip()
    for origin in os.getenv(
        "MARKETVIEW_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]

# EMSX 订单导出收件箱（057 DL-01）：交易员盘中手工导出的 CSV 落盘目录。
# 目录在仓库外、只增不删（留档）；未配置时盘前单端点返回空数据 + 说明，
# 不设默认值（不同机器导出路径不同，禁止硬编码）。
EXPORT_INBOX_DIR: str = os.getenv("EMSXVIEW_EXPORT_INBOX_DIR", "")
