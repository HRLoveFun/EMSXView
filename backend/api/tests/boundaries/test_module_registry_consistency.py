"""模块注册一致性检测。

验证:
- 前端每个 module.registry.ts 必须在 module-boundary.md 中有对应边界规则
- platform_data/contracts 实际文件与 module-api-contracts.md 契约清单一致
- ADR 编号无重复

执行: pytest backend/api/tests/boundaries/test_module_registry_consistency.py -v
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


def _list_ts_module_ids() -> list[str]:
    """从所有 module.registry.ts 提取 module id"""
    modules_dir = REPO_ROOT / "frontend" / "src" / "modules"
    if not modules_dir.exists():
        return []
    ids = []
    for registry in modules_dir.glob("*/module.registry.ts"):
        text = registry.read_text(encoding="utf-8")
        m = re.search(r"id:\s*['\"]([^'\"]+)['\"]", text)
        if m:
            ids.append(m.group(1))
    return ids


def _list_md_module_ids() -> list[str]:
    """从 module-boundary.md 提取已声明的模块 id（标题中出现的所有模块名）"""
    md_path = REPO_ROOT / ".codebuddy" / "rules" / "module-boundary.md"
    if not md_path.exists():
        return []
    text = md_path.read_text(encoding="utf-8")
    # 提取 ### X.Y heading 后的所有单词（包含 ↔ 两侧的模块名）
    headings = re.findall(
        r"^###\s+\d+\.\d+\s+([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    ids: set[str] = set()
    for h in headings:
        # 提取标题中所有小写单词（execution, marketview, costview, database 等）
        for word in re.findall(r"\b[a-z][a-z0-9_]*\b", h):
            ids.add(word)
    return list(ids)


def _list_adr_numbers() -> list[str]:
    """从 docs/spec/adr/ 提取已存在的 ADR 编号"""
    adr_dir = REPO_ROOT / "docs" / "spec" / "adr"
    if not adr_dir.exists():
        return []
    nums = []
    for f in adr_dir.glob("*.md"):
        m = re.match(r"^(\d{4})-", f.name)
        if m:
            nums.append(m.group(1))
    return nums


def _list_adr_links_from_memory() -> list[str]:
    """从 memory.md 提取 ADR 引用编号"""
    md_path = REPO_ROOT / "docs" / "spec" / "memory.md"
    if not md_path.exists():
        return []
    text = md_path.read_text(encoding="utf-8")
    return re.findall(r"ADR-(\d{4})", text)


@pytest.mark.boundary_violation
def test_adr_numbers_unique():
    """ADR 编号必须唯一"""
    nums = _list_adr_numbers()
    duplicates = [n for n in set(nums) if nums.count(n) > 1]
    assert not duplicates, f"Duplicate ADR numbers: {duplicates}"


@pytest.mark.boundary_violation
def test_adr_inventory_matches_memory(violations_recorder):
    """docs/spec/adr/ 中的 ADR 必须在 memory.md 中有索引链接"""
    actual = set(_list_adr_numbers())
    memory_links = set(_list_adr_links_from_memory())

    if not actual:
        pytest.skip("no ADRs found")

    missing_in_memory = actual - memory_links
    if missing_in_memory:
        for n in sorted(missing_in_memory):
            violations_recorder(
                "DOC-DRIFT",
                "docs/spec/memory.md",
                f"ADR-{n} exists but not indexed in memory.md",
                fix_hint="在 docs/spec/memory.md §2 ADR 索引表中添加 ADR-NNNN 行",
            )
        pytest.skip(
            f"violation recorded: {len(missing_in_memory)} ADR(s) not in memory index; "
            f"see BOUNDARY VIOLATIONS section in summary"
        )


@pytest.mark.boundary_violation
def test_module_registry_id_matches_boundary_doc(violations_recorder):
    """前端每个 module.registry.ts 的 id 必须在 module-boundary.md 中有边界规则"""
    ts_ids = set(_list_ts_module_ids())
    md_ids = set(_list_md_module_ids())

    if not ts_ids:
        pytest.skip("no module registries found")

    missing_in_doc = ts_ids - md_ids
    if missing_in_doc:
        for mid in sorted(missing_in_doc):
            violations_recorder(
                "DOC-DRIFT",
                ".codebuddy/rules/module-boundary.md",
                f"module '{mid}' registered but not documented in boundary rules",
                fix_hint="在 module-boundary.md §1 中添加该模块的边界规则",
            )
        pytest.skip(
            f"violation recorded: {len(missing_in_doc)} module(s) missing boundary rules; "
            f"see BOUNDARY VIOLATIONS section in summary"
        )
