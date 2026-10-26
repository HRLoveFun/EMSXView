"""MarketView JWT 校验（A04/M2）。

与 core backend 共用 `JWT_SECRET`（HS256）；未配置密钥 / 无 token / 校验失败
一律 401。本服务不复制后端角色矩阵：只验证身份（handoff 写端点）。
"""

from __future__ import annotations

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

security = HTTPBearer(auto_error=False)


async def require_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """校验 Bearer JWT（fail-closed：密钥缺失同样 401）。"""
    if credentials is None or not config.JWT_SECRET:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return jwt.decode(
            credentials.credentials,
            config.JWT_SECRET,
            algorithms=[config.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
