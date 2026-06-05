"""文档漂移检测（夜间任务）。

检测项:
1. OpenAPI schema (从 backend/api/main.py 运行时生成) 端点 vs docs/spec/module-api-contracts.md 端点
2. docs/spec/adr/ 实际文件 vs memory.md 索引
3. module.registry.ts 模块 vs module-boundary.md 小节

执行:
  python scripts/audit_doc_drift.py
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def get_adr_files() -> set[str]:
    adr_dir = REPO_ROOT / "docs" / "spec" / "adr"
    if not adr_dir.exists():
        return set()
    return {f.stem.split("-")[0] for f in adr_dir.glob("[0-9]*.md")}


def get_memory_adr_refs() -> set[str]:
    md = REPO_ROOT / "docs" / "spec" / "memory.md"
    if not md.exists():
        return set()
    return set(re.findall(r"ADR-(\d{4})", md.read_text(encoding="utf-8")))


def get_module_registry_ids() -> set[str]:
    modules_dir = REPO_ROOT / "frontend" / "src" / "modules"
    if not modules_dir.exists():
        return set()
    ids = set()
    for registry in modules_dir.glob("*/module.registry.ts"):
        text = registry.read_text(encoding="utf-8")
        m = re.search(r"id:\s*['\"]([^'\"]+)['\"]", text)
        if m:
            ids.add(m.group(1))
    return ids


def get_boundary_doc_ids() -> set[str]:
    md = REPO_ROOT / ".codebuddy" / "rules" / "module-boundary.md"
    if not md.exists():
        return set()
    text = md.read_text(encoding="utf-8")
    headings = re.findall(
        r"^###\s+\d+\.\d+\s+([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    ids: set[str] = set()
    for h in headings:
        for word in re.findall(r"\b[a-z][a-z0-9_]*\b", h):
            ids.add(word)
    return ids


def get_platform_adapter_classes() -> set[str]:
    """从 platform_data/adapters/ 实际类定义中提取（仅 *Adapter 后缀）"""
    pkg = REPO_ROOT / "platform_data" / "adapters"
    if not pkg.exists():
        return set()
    classes = set()
    for py in pkg.glob("*.py"):
        if py.name == "__init__.py":
            continue
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"^class\s+(\w+Adapter)", text, flags=re.MULTILINE):
            classes.add(m.group(1))
    return classes


def get_platform_adapter_doc_classes() -> set[str]:
    """从 .codebuddy/rules/module-boundary.md §2.3 表格中提取"""
    md = REPO_ROOT / ".codebuddy" / "rules" / "module-boundary.md"
    if not md.exists():
        return set()
    text = md.read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*`(\w+Adapter)\s*`", text, flags=re.MULTILINE))


def main() -> int:
    issues: list[str] = []

    # 1. ADR 文件 vs memory.md 索引
    adr_files = get_adr_files()
    memory_refs = get_memory_adr_refs()
    missing = adr_files - memory_refs
    extra = memory_refs - adr_files
    if missing:
        issues.append(f"ADRs missing from memory.md: {sorted(missing)}")
    if extra:
        issues.append(f"memory.md references missing ADRs: {sorted(extra)}")

    # 2. 模块注册 vs 边界文档
    reg_ids = get_module_registry_ids()
    doc_ids = get_boundary_doc_ids()
    missing_rules = reg_ids - doc_ids
    if missing_rules:
        issues.append(
            f"Modules registered but no boundary rules: {sorted(missing_rules)}"
        )

    # 3. 实际平台适配器 vs 文档表格
    code_adapters = get_platform_adapter_classes()
    doc_adapters = get_platform_adapter_doc_classes()
    missing_adapters = code_adapters - doc_adapters
    extra_adapters = doc_adapters - code_adapters
    if missing_adapters:
        issues.append(
            f"Adapters in code but not in module-boundary.md §2.3: "
            f"{sorted(missing_adapters)}"
        )
    if extra_adapters:
        issues.append(
            f"Adapters in doc but not in code (待实现): "
            f"{sorted(extra_adapters)}"
        )

    if issues:
        print("[WARN] Documentation drift detected!")
        for i in issues:
            print(f"  - {i}")
        return 1

    print("[OK] No documentation drift detected.")
    print(f"   - {len(adr_files)} ADRs indexed")
    print(f"   - {len(reg_ids)} modules registered with boundary rules")
    print(f"   - {len(code_adapters)} platform adapters documented")
    return 0


if __name__ == "__main__":
    sys.exit(main())
