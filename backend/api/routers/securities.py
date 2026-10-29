"""证券参考数据端点：名称字段（默认中文简称，可选英文短名）。

MarketView 微服务没有 Bloomberg 会话（只读数据层），池板/盘前单/监控台的「Name」列
经这里取数；服务层有进程内缓存，重复请求不会重复打终端。只读、无写路径。
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from deps import verify_token
from schemas import ApiResponse
from services.bloomberg.security_names import (
    DEFAULT_FIELD,
    SUPPORTED_FIELDS,
    SecurityNamesService,
)

router = APIRouter(tags=["Securities"])

#: 单次请求的 ticker 上限（一次池板最多 100 行，留足余量）
MAX_TICKERS = 300

_name_service = SecurityNamesService()


def parse_tickers(raw: str | None) -> list[str]:
    """逗号分隔 → 列表；空值或超限直接 400（不静默截断）。"""
    items = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not items:
        raise HTTPException(status_code=400, detail="tickers 不能为空")
    if len(items) > MAX_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tickers ({len(items)}); max {MAX_TICKERS} per request",
        )
    return items


def parse_field(raw: str | None) -> str:
    """字段白名单校验：只允许 SUPPORTED_FIELDS 内的名称字段。"""
    field = (raw or DEFAULT_FIELD).strip().upper()
    if field not in SUPPORTED_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported field {field}; allowed: {sorted(SUPPORTED_FIELDS)}",
        )
    return field


@router.get("/api/securities/names", response_model=ApiResponse)
async def get_security_names(
    tickers: str = Query(..., description="逗号分隔的 Bloomberg ticker（如 `AAPL US Equity`）"),
    field: str = Query(
        default=DEFAULT_FIELD,
        description="名称字段：NAME_CHINESE_SIMPLIFIED（默认）或 SHORT_NAME",
    ),
    user: dict = Depends(verify_token),
) -> ApiResponse:
    """返回 `{names: {ticker: 名称}, missing: [...], field}`；解析不到的进 missing。"""
    wanted = parse_tickers(tickers)
    resolved_field = parse_field(field)
    names, missing = await asyncio.to_thread(_name_service.get_names, wanted, resolved_field)
    return ApiResponse(
        success=True,
        data={"names": names, "missing": missing, "field": resolved_field},
        message=f"resolved {len(names)}/{len(wanted)} name(s) via {resolved_field}",
    )
