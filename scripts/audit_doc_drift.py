"""文档漂移审计。

分级模型（2026-08-26 升级）:
- CORE（退出码 1，CI 硬阻断）: 架构契约类漂移 ——
  memory.md 的 ADR 索引 / module-boundary.md 边界规则与适配器表 /
  AGENTS.md ↔ CODEBUDDY.md 同步
- WARN（退出码 0，PR 审查 + 周报跟进）: 非阻断类漂移 ——
  如文档先于代码的「待实现」适配器条目（ADR-0013 认可的合法状态）

检测项:
1. docs/spec/adr/ 实际文件 vs docs/spec/memory.md 索引           [CORE]
2. module.registry.ts 模块 vs module-boundary.md 小节             [CORE]
3. platform_data/adapters 实际类 vs module-boundary.md §2.3 表格  [CORE 缺失 / WARN 多余]
4. AGENTS.md vs CODEBUDDY.md 内容一致性                           [CORE]

执行:
  python scripts/audit_doc_drift.py           # 审计模式（CI / 周报共用）
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Windows 控制台 (cp1252) 下强制 UTF-8 stdout, 避免中文报告触发 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")


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


def _normalized_text(path: Path) -> str:
    """读取文本并归一化行尾 (CRLF/LF)。

    pre-commit hook 以 `git show :AGENTS.md > CODEBUDDY.md` 方式写入,
    工作区两文件可能存在行尾差异, 字节级比较会误报。
    """
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def is_agents_codebuddy_in_sync() -> bool:
    """AGENTS.md 为规范源；两份内容不一致即核心漂移（hook 未生效时的 CI 兜底）"""
    ag = REPO_ROOT / "AGENTS.md"
    cb = REPO_ROOT / "CODEBUDDY.md"
    if not ag.exists() or not cb.exists():
        # 文件缺失属结构性问题，不在此判定
        return True
    return _normalized_text(ag) == _normalized_text(cb)


def main() -> int:
    core_issues: list[str] = []
    warn_issues: list[str] = []

    # 1. ADR 文件 vs memory.md 索引 [CORE]
    adr_files = get_adr_files()
    memory_refs = get_memory_adr_refs()
    missing = adr_files - memory_refs
    extra = memory_refs - adr_files
    if missing:
        core_issues.append(f"ADRs missing from memory.md: {sorted(missing)}")
    if extra:
        core_issues.append(f"memory.md references missing ADRs: {sorted(extra)}")

    # 2. 模块注册 vs 边界文档 [CORE]
    reg_ids = get_module_registry_ids()
    doc_ids = get_boundary_doc_ids()
    missing_rules = reg_ids - doc_ids
    if missing_rules:
        core_issues.append(
            f"Modules registered but no boundary rules: {sorted(missing_rules)}"
        )

    # 3. 实际平台适配器 vs 文档表格 [CORE 缺失 / WARN 多余]
    code_adapters = get_platform_adapter_classes()
    doc_adapters = get_platform_adapter_doc_classes()
    missing_adapters = code_adapters - doc_adapters
    extra_adapters = doc_adapters - code_adapters
    if missing_adapters:
        core_issues.append(
            f"Adapters in code but not in module-boundary.md §2.3: "
            f"{sorted(missing_adapters)}"
        )
    if extra_adapters:
        warn_issues.append(
            f"Adapters in doc but not in code (待实现, 参见 ADR-0013): "
            f"{sorted(extra_adapters)}"
        )

    # 4. AGENTS.md ↔ CODEBUDDY.md 同步 [CORE]
    if not is_agents_codebuddy_in_sync():
        core_issues.append(
            "AGENTS.md 与 CODEBUDDY.md 内容不一致 (规范源为 AGENTS.md; "
            "请以 AGENTS.md 覆盖 CODEBUDDY.md 或配置 core.hooksPath .githooks)"
        )

    if core_issues:
        print("[FAIL] 核心文档漂移 (CI 硬阻断):")
        for i in core_issues:
            print(f"  - {i}")
    if warn_issues:
        print("[WARN] 非核心文档漂移 (由 PR 审查 / 每周漂移报告跟进):")
        for i in warn_issues:
            print(f"  - {i}")
    if not core_issues and not warn_issues:
        print("[OK] No documentation drift detected.")
        print(f"   - {len(adr_files)} ADRs indexed")
        print(f"   - {len(reg_ids)} modules registered with boundary rules")
        print(f"   - {len(code_adapters)} platform adapters documented")
        print("   - AGENTS.md == CODEBUDDY.md")
        return 0

    return 1 if core_issues else 0


if __name__ == "__main__":
    sys.exit(main())
