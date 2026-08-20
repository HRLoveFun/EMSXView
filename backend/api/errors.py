"""统一错误分类与安全 detail 映射 (M5)。

目标:
    - 内部异常绝不原样泄漏到 API 响应 (文件路径/堆栈/第三方错误文本)
    - 每个可预见的失败归类为稳定错误码, 前端可按码处理
    - DEBUG 模式下透传原始 detail 便于开发排查

使用:
    from errors import error_detail, ErrorCode

    raise HTTPException(
        status_code=500,
        detail=error_detail(ErrorCode.BLOOMBERG_ERROR, str(e)),
    )
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from config import settings

logger = logging.getLogger("main")


class ErrorCode:
    """稳定错误分类码 — 用于 API 响应的 error_code 字段。"""

    INTERNAL = "INTERNAL_ERROR"
    BLOOMBERG = "BROKER_ERROR"
    COMPLIANCE = "COMPLIANCE_ERROR"
    PERSISTENCE = "PERSISTENCE_ERROR"
    HANDOFF = "HANDOFF_ERROR"
    VALIDATION = "VALIDATION_ERROR"


# 5xx 状态码下允许透传 detail 的错误类型 — 这些 detail 不包含内部信息
_SAFE_DETAIL_CODES = {
    ErrorCode.COMPLIANCE,   # 合规拒绝原因需要展示给交易员
    ErrorCode.VALIDATION,
}

# 错误类型 → 默认安全 detail 文案 (非 DEBUG 模式)
_DEFAULT_DETAILS: dict[str, str] = {
    ErrorCode.INTERNAL: "Internal server error",
    ErrorCode.BLOOMBERG: "Bloomberg EMSX service unavailable",
    ErrorCode.COMPLIANCE: "Order rejected by compliance policy",
    ErrorCode.PERSISTENCE: "Database persistence unavailable",
    ErrorCode.HANDOFF: "Cross-module handoff failed",
    ErrorCode.VALIDATION: "Request validation failed",
}


def error_detail(code: str, raw_detail: Any = None) -> str:
    """构造安全的 error detail。

    - DEBUG 模式: 透传 raw_detail (便于开发排查)
    - 非 DEBUG 且 code 在安全白名单: 保留 raw_detail (如合规拒绝原因)
    - 其余: 返回 code 对应的默认文案, 原始信息只进日志
    """
    if settings.DEBUG:
        return str(raw_detail) if raw_detail is not None else _DEFAULT_DETAILS[code]
    if code in _SAFE_DETAIL_CODES and raw_detail is not None:
        return str(raw_detail)
    if raw_detail is not None:
        logger.error("内部异常已遮蔽 (code=%s): %s", code, raw_detail)
    return _DEFAULT_DETAILS[code]


def classify_exception(exc: Exception) -> str:
    """按异常类型归类为稳定错误码 (供全局 handler 使用)。"""
    module = exc.__class__.__module__ or ""
    name = exc.__class__.__name__
    if module.startswith("blpapi") or "Bloomberg" in name:
        return ErrorCode.BLOOMBERG
    return ErrorCode.INTERNAL


def http_error(status_code: int, code: str, raw_detail: Any = None) -> HTTPException:
    """构造带安全 detail 的 HTTPException。"""
    return HTTPException(status_code=status_code, detail=error_detail(code, raw_detail))
