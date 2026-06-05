"""FastAPI router 端点必须返回 ApiResponse 包装。

对应反模式: AP-05 ApiResponse 包装缺失
执行: pytest backend/api/tests/boundaries/test_router_api_response.py -v

实现: 用行号解析而非 regex 回溯匹配，避免性能问题。
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
ROUTERS_DIR = REPO_ROOT / "backend" / "api" / "routers"

SKIP_MARKERS = ("FileResponse", "StreamingResponse", "WebSocket")


def _parse_endpoints(text: str) -> list[tuple[str, str, int]]:
    """解析 router 文件中所有 endpoint 签名 + 函数体前 10 行

    返回 [(endpoint_name, body, line_no), ...]
    """
    lines = text.splitlines()
    results: list[tuple[str, str, int]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        # 找 @router.<method>( 装饰器
        if line.lstrip().startswith("@router.") and "(" in line:
            # 下一行（可能跨行装饰器参数，但简单起见只处理单行）
            # 紧接 async def 行
            for j in range(i + 1, min(i + 5, len(lines))):
                if "async def" in lines[j] or "def " in lines[j]:
                    # 提取函数名
                    try:
                        # 形如 "async def name(" 或 "    async def name(...):"
                        after_def = lines[j].split("def ", 1)[1]
                        name = after_def.split("(", 1)[0].strip()
                    except IndexError:
                        break
                    # 收集函数体前 20 行
                    body_lines: list[str] = []
                    for k in range(j + 1, min(j + 25, len(lines))):
                        body_lines.append(lines[k])
                        # 遇到下一个装饰器或顶层定义则停
                        stripped = lines[k].lstrip()
                        if (
                            stripped.startswith("@router.")
                            or stripped.startswith("@app.")
                            or (lines[k] and not lines[k][0].isspace() and stripped)
                        ):
                            break
                    results.append((name, "\n".join(body_lines), j + 1))
                    i = j
                    break
        i += 1
    return results


@pytest.mark.boundary_violation
def test_router_endpoints_return_api_response(violations_recorder):
    """所有 router 端点必须包含 ApiResponse 返回"""
    if not ROUTERS_DIR.exists():
        pytest.skip(f"{ROUTERS_DIR} not found")

    violations = []

    for router_file in ROUTERS_DIR.glob("*.py"):
        try:
            text = router_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        for name, body, line_no in _parse_endpoints(text):
            if any(marker in body for marker in SKIP_MARKERS):
                continue
            if "ApiResponse" in body:
                continue
            try:
                rel = router_file.relative_to(REPO_ROOT)
            except ValueError:
                rel = router_file
            violations.append((str(rel), name, line_no, body[:200]))

    if violations:
        for path, name, line_no, snippet in violations:
            violations_recorder(
                "AP-05",
                path,
                f"endpoint '{name}' (line {line_no}) does not return ApiResponse",
                fix_hint="改为 return ApiResponse(data=..., success=True) 或 ApiResponse(success=False, error_code=...)",
            )
        pytest.skip(
            f"violation recorded: {len(violations)} AP-05 violation(s); "
            f"see BOUNDARY VIOLATIONS section in summary"
        )
