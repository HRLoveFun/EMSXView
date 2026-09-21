"""错误载荷可见性 —— 5xx 遮蔽精度收敛（``backend/api/errors.py``）。

锁定 M5 的原始意图（内部异常不外泄）与 2026-09-21 的精度修正（业务降级
信号必须下发），避免「一刀切遮蔽」回归。
"""

import pytest
from pydantic import ValidationError

from errors import (
    CLIENT_SAFE_ERROR_CODES,
    MASKED_ERROR_MESSAGE,
    visible_error_detail,
)
from schemas import ApiResponse


@pytest.mark.parametrize("code", sorted(CLIENT_SAFE_ERROR_CODES))
def test_business_error_codes_pass_through(code: str) -> None:
    """白名单内的结构化 detail 必须下发，且渲染为 [code] message。"""
    error, masked = visible_error_detail(
        {"code": code, "message": "数据尚未生成，请先触发 Runner"},
        status_code=503, debug=False,
    )
    assert (error, masked) == (f"[{code}] 数据尚未生成，请先触发 Runner", False)


def test_business_code_without_message_is_still_visible() -> None:
    error, masked = visible_error_detail({"code": "query_timeout"}, status_code=503, debug=False)
    assert (error, masked) == ("[query_timeout]", False)


def test_unknown_structured_code_is_masked() -> None:
    """未登记的错误码 fail-closed：退回遮蔽，不泄漏内部细节。"""
    error, masked = visible_error_detail(
        {"code": "sqlite_error", "message": "no such table: tca_route_summary"},
        status_code=503, debug=False,
    )
    assert (error, masked) == (MASKED_ERROR_MESSAGE, True)


def test_internal_5xx_string_detail_is_masked() -> None:
    error, masked = visible_error_detail(
        "TCA analysis error: sqlite3.OperationalError: disk I/O error",
        status_code=500, debug=False,
    )
    assert (error, masked) == (MASKED_ERROR_MESSAGE, True)


def test_4xx_string_detail_is_kept() -> None:
    assert visible_error_detail("order not found", status_code=404, debug=False) == (
        "order not found", False,
    )


def test_4xx_structured_detail_is_serialized() -> None:
    """400 + 结构化 detail（预交易合规 violations）不得原样传 dict。

    ``ApiResponse.error`` 只接受 ``str``，传 dict 会抛 Pydantic 校验错误，
    使 400 退化为无信息的 500 —— 规范化后的 JSON 串可正常下发。
    """
    error, masked = visible_error_detail(
        {"message": "Pre-trade compliance check failed", "violations": [{"rule": "max_notional"}]},
        status_code=400, debug=False,
    )
    assert masked is False
    assert "Pre-trade compliance check failed" in error
    assert "max_notional" in error
    assert ApiResponse(success=False, error=error).error == error


def test_debug_mode_passes_detail_through() -> None:
    error, masked = visible_error_detail({"code": "sqlite_error"}, status_code=500, debug=True)
    assert masked is False
    assert "sqlite_error" in error


def test_api_response_rejects_structured_error_payload() -> None:
    """回归锚点：结构化 error 无法通过 ApiResponse 校验（故必须先规范化）。"""
    with pytest.raises(ValidationError):
        ApiResponse(success=False, error={"code": "data_not_ready"})
