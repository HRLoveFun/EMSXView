"""PowerShell 脚本编码一致性检测（Windows PowerShell 5.1 兼容）。

对应实测问题（2026-09-16，specs/016-wt-finish-robustness）：

Windows PowerShell 5.1 读取**无 BOM** 的文件时按 ANSI(cp1252) 解码。脚本中的中文（UTF-8 多字节）
会被误解析 —— 其中字节 0x93/0x94 在 cp1252 中对应智能引号 “ ”，而 PowerShell 把智能引号当字符串
定界符，字符串字面量因此提前结束，产生 ParserError。实测：

- `wt-list.ps1` → ``Missing '=' operator after key in hash literal``
- `wt-new.ps1`  → ``The string is missing the terminator``
- PowerShell Core（pwsh）下均正常 —— 故此前长期未暴露。

影响面：`scripts/devtools/wt-install-schedule.ps1` 注册的每日同步任务以 `powershell`（5.1）调用
`wt-sync.ps1`；`.bat` 启动器同样以 `powershell` 调用 `scripts/ops/service-manager.ps1`。

约束：`scripts/**/*.ps1` 若含非 ASCII 字节，必须保存为 **UTF-8 with BOM**（BOM 使 5.1 也按 UTF-8 解码）。

执行: pytest backend/api/tests/boundaries/test_ps1_encoding.py -v
"""
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SCAN_ROOT = REPO_ROOT / "scripts"
BOM = b"\xef\xbb\xbf"


def _ps1_files() -> list[Path]:
    """scripts/ 下全部 PowerShell 脚本。"""
    if not SCAN_ROOT.exists():
        return []
    return sorted(SCAN_ROOT.rglob("*.ps1"))


@pytest.mark.boundary_violation
def test_ps1_files_with_non_ascii_have_bom(violations_recorder):
    """含非 ASCII 的 .ps1 必须带 UTF-8 BOM，否则 5.1 按 ANSI 解码会解析失败。"""
    files = _ps1_files()
    if not files:
        pytest.skip("scripts/ 下未找到 .ps1")

    offenders = []
    for path in files:
        data = path.read_bytes()
        if data.startswith(BOM):
            continue
        if any(byte > 0x7F for byte in data):
            offenders.append(path)

    if offenders:
        for path in offenders:
            violations_recorder(
                "PS1-ENC",
                path.relative_to(REPO_ROOT).as_posix(),
                "含非 ASCII 但缺少 UTF-8 BOM（Windows PowerShell 5.1 会按 ANSI 解码并解析失败）",
                fix_hint="以 UTF-8 with BOM 另存；或改为纯 ASCII 内容",
            )
        pytest.fail(
            f"{len(offenders)} PS1-ENC violation(s): "
            + "; ".join(p.relative_to(REPO_ROOT).as_posix() for p in offenders)
        )


@pytest.mark.boundary_violation
def test_ps1_files_are_utf8_decodable():
    """全部 .ps1 必须可按 UTF-8 解码（排除 GBK/ANSI 混存）。"""
    files = _ps1_files()
    if not files:
        pytest.skip("scripts/ 下未找到 .ps1")

    broken = []
    for path in files:
        try:
            path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            broken.append(path.relative_to(REPO_ROOT).as_posix())

    assert not broken, f"非 UTF-8 编码的脚本: {broken}"
