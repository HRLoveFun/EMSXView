"""HTTP 错误载荷可见性 —— 5xx 遮蔽精度收敛（M5 的精确化实现）。

背景（2026-09-21 定位）：M5 引入的「非 DEBUG 模式遮蔽 5xx detail」按
``status_code >= 500`` 一刀切，把**业务降级信号**（503 + 结构化
``{"code", "message"}``，如 ``data_not_ready`` / ``query_timeout``）也抹成
``"Internal server error"``。CostView 前端因此长期只能显示
"Internal server error"，既无法区分「数据未生成」与「服务内部故障」，
也看不到后端给出的可操作提示（触发 EMSXDataPipeline Runner）。

本模块把遮蔽收敛为三条规则：

1. 结构化业务降级 detail（``code`` 在 :data:`CLIENT_SAFE_ERROR_CODES` 内）
   → 放行，渲染为 ``[<code>] <message>``（与前端 ``readError`` 的结构化
   分支同格式，两种部署形态下文案一致）；
2. 其余 5xx → 遮蔽为 ``"Internal server error"``（内部异常不外泄）；
3. 4xx → 字符串原样；结构化 detail（如预交易合规 ``violations``）序列化为
   JSON 串 —— ``ApiResponse.error`` 只接受 ``str``，直接传 dict 会触发
   Pydantic 校验错误，反而把 400 变成无信息的 500。

白名单为**显式枚举**（fail-closed）：新增业务错误码必须在此登记，否则退回
「遮蔽」这一保守行为。
"""

from __future__ import annotations

import json
from typing import Any, Optional, Tuple

#: 面向调用方的业务降级错误码白名单。
#: 与 ``CostView/api/routers/costview.py``（data_not_ready / query_timeout /
#: data_source_unavailable）、``CostView/api/routers/monitoring.py``
#: （bdib_scan_timeout / bdib_scan_failed）抛出的结构化 detail 一一对应。
CLIENT_SAFE_ERROR_CODES: frozenset[str] = frozenset({
    "data_not_ready",
    "query_timeout",
    "data_source_unavailable",
    "bdib_scan_timeout",
    "bdib_scan_failed",
})

#: 内部异常的统一对外文案（不得携带异常内容）。
MASKED_ERROR_MESSAGE = "Internal server error"


def _format_business_detail(detail: dict) -> Optional[str]:
    """白名单命中的结构化 detail → ``[code] message``；未命中返回 ``None``。"""
    code = detail.get("code")
    if not isinstance(code, str) or code not in CLIENT_SAFE_ERROR_CODES:
        return None
    message = str(detail.get("message") or "").strip()
    return f"[{code}] {message}" if message else f"[{code}]"


def visible_error_detail(
    detail: Any, *, status_code: int, debug: bool,
) -> Tuple[str, bool]:
    """规范化 ``HTTPException.detail`` → ``(下发文案, 是否已遮蔽)``。

    ``masked=True`` 表示原 detail 属内部异常、已替换为
    :data:`MASKED_ERROR_MESSAGE`，调用方应据此记录日志留痕。
    """
    if isinstance(detail, dict):
        business = _format_business_detail(detail)
        if business is not None:
            return business, False
    if debug or status_code < 500:
        if detail is None or isinstance(detail, str):
            return (detail or ""), False
        return json.dumps(detail, ensure_ascii=False, default=str), False
    return MASKED_ERROR_MESSAGE, True
