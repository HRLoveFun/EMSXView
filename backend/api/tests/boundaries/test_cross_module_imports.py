"""跨模块 deep import 检测。

对应反模式:
- AP-01 跨域 deep import
- AP-08 跨域调用下划线方法
- AGENTS.md 中的"禁止 from CostView.src.* import"

执行: pytest backend/api/tests/boundaries/test_cross_module_imports.py -v
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]

# ── 检测规则: (扫描根, 适配后缀, 禁止的 import 前缀, 规则 ID, 描述, 修复建议, 豁免清单) ──
# 豁免清单为 REPO_ROOT 相对路径（posix 风格）；列入豁免的文件允许命中前缀。
# 豁免仅限设计内受许可的深导入（如 DI 注册、桥接入口），新增豁免须在注释说明理由。
PYTHON_RULES = [
    (
        REPO_ROOT / "backend" / "api",
        "*.py",
        "CostView.src",
        "AP-01",
        "backend → CostView deep import",
        "改走 platform_data.<domain>.*",
        set(),
    ),
    (
        REPO_ROOT / "backend" / "api",
        "*.py",
        "DataPipeline.",
        "AP-01",
        "backend → DataPipeline deep import",
        "改走 platform_data.config_bridge / register_costview_bridge_dependencies()",
        {
            # 豁免：main.py 启动时向 config_bridge 注册 DataPipeline Config（DI 注册，
            # 项目指南约定"应从 DataPipeline/config.Config 导入"，是设计内入口）
            "backend/api/main.py",
        },
    ),
    (
        REPO_ROOT / "platform_data",
        "*.py",
        "CostView.src",
        "AP-01",
        "platform_data → CostView deep import",
        "platform_data 内部应保持中立，避免直接依赖业务模块",
        {
            # 豁免：tca_bridge 是集中封装 CostView.src 深导入的唯一桥接入口
            #（e2c382e 设计，backend 仅依赖 platform_data，不直接依赖 CostView.src）
            "platform_data/adapters/tca_bridge.py",
        },
    ),
]

TS_RULES = [
    (
        REPO_ROOT / "frontend" / "src" / "modules" / "execution",
        "*.tsx",
        "@costview",
        "AP-01",
        "execution → costview 跨模块 import",
        "改走 navigateTo / useHandoffContracts / @shared/types",
        set(),
    ),
    (
        REPO_ROOT / "frontend" / "src" / "modules" / "execution",
        "*.ts",
        "@costview",
        "AP-01",
        "execution → costview 跨模块 import",
        "改走 navigateTo / useHandoffContracts / @shared/types",
        set(),
    ),
    (
        REPO_ROOT / "frontend" / "src" / "modules" / "costview",
        "*.tsx",
        "@execution",
        "AP-01",
        "costview → execution 跨模块 import",
        "改走 navigateTo / useHandoffContracts / @shared/types",
        set(),
    ),
    (
        REPO_ROOT / "frontend" / "src" / "modules" / "costview",
        "*.ts",
        "@execution",
        "AP-01",
        "costview → execution 跨模块 import",
        "改走 navigateTo / useHandoffContracts / @shared/types",
        set(),
    ),
]


def _scan_python_imports(file: Path):
    """提取 Python 文件的 from-import"""
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return re.findall(
        r"^\s*from\s+([\w.]+)\s+import",
        text,
        flags=re.MULTILINE,
    )


def _scan_ts_imports(file: Path):
    """提取 TS/TSX 文件的 from-import"""
    try:
        text = file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    return re.findall(r"from\s+['\"]([^'\"]+)['\"]", text)


@pytest.mark.boundary_violation
@pytest.mark.parametrize(
    "base_dir,suffix,forbidden,rule_id,message,fix_hint,exempt",
    PYTHON_RULES + TS_RULES,
    ids=[r[3] + ":" + str(r[0].name) + ":" + r[2] for r in PYTHON_RULES + TS_RULES],
)
def test_no_forbidden_imports(
    violations_recorder, enforcement_mode, base_dir, suffix, forbidden, rule_id,
    message, fix_hint, exempt
):
    """block 模式（默认）：检测到违规即 fail，CI 生效；record/warn 仅记录"""
    if not base_dir.exists():
        pytest.skip(f"{base_dir} not found")

    scanner = _scan_python_imports if suffix == "*.py" else _scan_ts_imports

    violations = []
    for f in base_dir.rglob(suffix):
        try:
            rel = f.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            rel = str(f)
        if rel in exempt:
            continue
        for imp in scanner(f):
            if imp and imp.startswith(forbidden):
                violations.append((rel, imp))

    if violations:
        for path, imp in violations:
            violations_recorder(
                rule_id,
                path,
                f"import '{imp}' is forbidden ({message})",
                fix_hint=fix_hint,
            )
        if enforcement_mode == "block":
            pytest.fail(
                f"{len(violations)} {rule_id} violation(s) [{message}]: "
                + "; ".join(f"{p} -> {i}" for p, i in violations)
            )
        pytest.skip(
            f"violation recorded: {len(violations)} {rule_id} violation(s); "
            f"see BOUNDARY VIOLATIONS section in summary"
        )


# ── 跨域调用下划线方法检测 ──
UNDERSCORE_RULES = [
    (
        REPO_ROOT / "backend",
        "*.py",
        r"platform_data\.\w+\.\w+_\w+",
        "AP-08",
        "调用 platform_data 适配器的下划线方法",
    ),
    (
        REPO_ROOT / "frontend" / "src",
        "*.ts",
        r"platform_data\.\w+\.\w+_\w+",
        "AP-08",
        "调用 platform_data 适配器的下划线方法",
    ),
]


@pytest.mark.boundary_violation
@pytest.mark.parametrize(
    "base_dir,suffix,pattern,rule_id,message",
    UNDERSCORE_RULES,
    ids=[r[3] + ":" + str(r[0].name) for r in UNDERSCORE_RULES],
)
def test_no_underscore_adapter_access(
    violations_recorder, enforcement_mode, base_dir, suffix, pattern, rule_id, message
):
    if not base_dir.exists():
        pytest.skip(f"{base_dir} not found")

    violations = []
    for f in base_dir.rglob(suffix):
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(pattern, text):
            try:
                rel = f.relative_to(REPO_ROOT).as_posix()
            except ValueError:
                rel = str(f)
            violations.append((rel, m.group(0)))

    if violations:
        for path, snippet in violations:
            violations_recorder(
                rule_id,
                path,
                f"underscore method access: {snippet} ({message})",
                fix_hint="改用适配器公开 API（无下划线前缀）",
            )
        if enforcement_mode == "block":
            pytest.fail(
                f"{len(violations)} {rule_id} violation(s) [{message}]: "
                + "; ".join(f"{p} -> {s}" for p, s in violations)
            )
        pytest.skip(
            f"violation recorded: {len(violations)} {rule_id} violation(s); "
            f"see BOUNDARY VIOLATIONS section in summary"
        )
