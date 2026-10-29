"""文档结构与地图对账（七项）。

只查能机械对账的部分：地图路径是否存在、`.md` 是否被地图覆盖、被索引文档有无
元信息头、状态枚举与证据列、相对链接是否可解析、已失效说法是否回流。
**不评价**「写得好不好」。

检测项与失败级别:
1. AGENTS.md 存在且 docmap 块有数据行                                   [FAIL]
2. 地图每行路径存在（通配行跳过）                                       [FAIL]
3. 仓库内 `.md` 都被地图覆盖，或被 docmap:exclude 块的 glob 豁免         [FAIL]
4. 被索引的 `.md` 首部有 `> Lx | 权威：… | 不权威：…`                    [WARN]
5. 状态源表格的状态值合法，`已完成` 行证据列非空                         [FAIL]
6. 被地图覆盖的文档内，相对链接目标存在（豁免区不查）                    [WARN]
7. 被地图覆盖的文档不再出现已失效术语（ADR 正文与归档件除外）             [WARN]

执行:
  python scripts/doc_check.py            # 审计；退出码 0 通过（WARN 不计失败）
  python scripts/doc_check.py --strict   # WARN 也算失败
  python scripts/doc_check.py --root <dir>

退出码: 0 通过 / 1 有 FAIL（或 --strict 下有 WARN） / 64 用法错或找不到 AGENTS.md
"""
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# Windows 控制台 (cp1252) 下强制 UTF-8 stdout，避免中文报告触发 UnicodeEncodeError
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout.reconfigure(encoding="utf-8")

PRUNE_DIRS = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    ".venv",
    "__pycache__",
    ".pytest_cache",
}
MARK_BEGIN = "<!-- docmap:begin -->"
MARK_END = "<!-- docmap:end -->"
EXCL_BEGIN = "<!-- docmap:exclude:begin -->"
EXCL_END = "<!-- docmap:exclude:end -->"

# 状态枚举：本仓库的任务表用「待开始 / 部分完成 / 不排期」，与通用五值并存
STATUS_PREFIXES = (
    "未开始",
    "进行中",
    "待开始",
    "已完成",
    "部分完成",
    "受阻",
    "不排期",
    "已取消",
)
EVIDENCE_REQUIRED_PREFIXES = ("已完成", "部分完成")
EMPTY_EVIDENCE = {"", "-", "—", "待补", "见上文", "已测", "N/A", "n/a"}

LINK_RE = re.compile(r"\]\(([^)]+)\)")
CELL_SPLIT_RE = re.compile(r"\|")

# 检查 7：已失效术语 → 期望说法。新增条目时同步 docs/archive/<日期>/agents-invalidated-claims.md
FORBIDDEN_TERMS: dict[str, str] = {
    "EMSXVIEW_MERGE_MODULES": "已失效，可选路由用 EMSXVIEW_OPTIONAL_MODULES",
    "VITE_USE_MOCK": "已失效，mock 由 VITE_API_URL 是否为空决定",
    "CORS_ORIGINS": "实际变量名为 ALLOWED_ORIGINS",
    "tca_fallback.py": "已删除，降级由各查询层内置",
}
# 同一行出现这些词视为「在说明它已失效」，放行
FORBIDDEN_SKIP_TOKENS = ("已失效", "已废弃", "勿再引用", "已删除", "已迁移", "移除", "下线")
# ADR 正文保留历史决策原貌、归档件记录历史，均不参与检查 7
FORBIDDEN_SKIP_PREFIXES = ("docs/archive/", "docs/spec/adr/")
# 检查 6 不查归档目录：历史文档的图片/子文档链接按归档原则保留原样
LINK_SKIP_PREFIXES = ("docs/archive/",)


class Report:
    """收集 FAIL / WARN 并统一打印。"""

    def __init__(self) -> None:
        self.fail = 0
        self.warn = 0

    def ok(self, msg: str) -> None:
        print(f"  OK    {msg}")

    def bad(self, msg: str) -> None:
        print(f"  FAIL  {msg}")
        self.fail += 1

    def warnf(self, msg: str) -> None:
        print(f"  WARN  {msg}")
        self.warn += 1


def extract_block(text: str, begin: str, end: str) -> str:
    """取标记块内容；缺标记返回空串。"""
    start = text.find(begin)
    if start < 0:
        return ""
    stop = text.find(end, start)
    if stop < 0:
        return ""
    return text[start + len(begin) : stop]


def split_row(line: str) -> list[str]:
    """把表格行拆成单元格（去掉首尾竖线产生的空串）。"""
    raw = line.strip()
    if not raw.startswith("|"):
        return []
    cells = CELL_SPLIT_RE.split(raw)
    return [c.strip() for c in cells[1:-1]]


def clean_path(cell: str) -> str:
    """首列清洗：去反引号、把 [文字](路径) 还原成路径。"""
    text = cell.strip()
    if text.startswith("`") and text.endswith("`"):
        text = text[1:-1]
    link = re.fullmatch(r"\[([^\]]*)\]\(([^)]*)\)", text)
    if link:
        text = link.group(2)
    return text.strip()


def parse_map(text: str) -> list[str]:
    """docmap 块内的路径列（保持顺序、去重）。"""
    paths: list[str] = []
    for line in extract_block(text, MARK_BEGIN, MARK_END).splitlines():
        cells = split_row(line)
        if not cells:
            continue
        path = clean_path(cells[0])
        if not path or path == "路径":
            continue
        if set(path) <= set("-: "):
            continue
        if path not in paths:
            paths.append(path)
    return paths


def parse_excludes(text: str) -> list[str]:
    patterns = []
    for line in extract_block(text, EXCL_BEGIN, EXCL_END).splitlines():
        pat = line.strip()
        if pat and not pat.startswith("#"):
            patterns.append(pat)
    return patterns


def glob_to_regex(pattern: str) -> re.Pattern[str]:
    """把 glob 转正则：`**` 跨目录，`*` 不跨目录，`?` 单字符。"""
    out = ["^"]
    i = 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    out.append("$")
    return re.compile("".join(out))


def collect_markdown(root: Path) -> list[str]:
    """仓库内全部 `.md`（相对 posix 路径），跳过构建/依赖目录。"""
    found: list[str] = []
    for path in root.rglob("*.md"):
        rel_parts = path.relative_to(root).parts
        if any(part in PRUNE_DIRS for part in rel_parts):
            continue
        found.append(path.relative_to(root).as_posix())
    return sorted(found)


def covers(rel: str, path: str) -> bool:
    return rel == path or rel.startswith(path.rstrip("/") + "/")


def has_meta_header(file_path: Path) -> bool:
    try:
        head = file_path.read_text(encoding="utf-8-sig").splitlines()[:15]
    except OSError:
        return False
    for line in head:
        if line.startswith("> L") and "| 权威：" in line and "不权威：" in line:
            return True
    return False


def status_rows(text: str) -> list[list[str]]:
    """状态源表格的行：优先取「## 状态总览」小节，否则取全文表格。"""
    section = text
    match = re.search(r"^##\s*状态总览\s*$", text, flags=re.MULTILINE)
    if match:
        rest = text[match.end() :]
        nxt = re.search(r"^##\s", rest, flags=re.MULTILINE)
        section = rest[: nxt.start()] if nxt else rest
    rows = []
    for line in section.splitlines():
        cells = split_row(line)
        if len(cells) < 8:
            continue
        first = cells[0].replace("`", "")
        if not first or first in {"DL", "批次", "项"}:
            continue
        if set(first) <= set("-: "):
            continue
        rows.append(cells)
    return rows


def check_map_rows(report: Report, root: Path, paths: list[str]) -> None:
    if not paths:
        report.bad("检查 1：AGENTS.md 里没有可解析的 docmap 块（或块内没有数据行）")
        return
    report.ok(f"检查 1：docmap 块可解析（{len(paths)} 行）")

    missing = 0
    for path in paths:
        if "*" in path:
            continue
        if not (root / path.rstrip("/")).exists():
            report.bad(f"检查 2：地图路径不存在：{path}")
            missing += 1
    if missing == 0:
        report.ok(f"检查 2：地图路径全部存在（{len(paths)} 行）")


def check_coverage(report: Report, all_md: list[str], paths: list[str], patterns: list[str]) -> None:
    regs = [glob_to_regex(p) for p in patterns]
    orphans: list[str] = []
    for rel in all_md:
        if any(reg.match(rel) for reg in regs):
            continue
        if any(covers(rel, path) for path in paths if "*" not in path):
            continue
        orphans.append(rel)
    if not orphans:
        report.ok("检查 3：所有 .md 都在地图内或已豁免")
        return
    for rel in orphans[:5]:
        report.bad(f"检查 3：未被地图覆盖：{rel}")
    if len(orphans) > 5:
        report.bad(f"检查 3：另有 {len(orphans) - 5} 份未被覆盖（只列前 5 份）")


def check_meta_headers(report: Report, root: Path, paths: list[str]) -> None:
    missing: list[str] = []
    for path in paths:
        if "*" in path or not path.endswith(".md") or path == "AGENTS.md":
            continue
        file_path = root / path
        if not file_path.is_file():
            continue
        if not has_meta_header(file_path):
            missing.append(path)
    if not missing:
        report.ok("检查 4：被索引文档都有元信息头")
        return
    for path in missing[:5]:
        report.warnf(f"检查 4：缺元信息头：{path}（应为 > Lx | 权威：… | 不权威：…）")
    if len(missing) > 5:
        report.warnf(f"检查 4：另有 {len(missing) - 5} 份缺元信息头（只列前 5 份）")


def check_status(report: Report, root: Path, paths: list[str]) -> None:
    source = next(
        (p for p in paths if p.endswith("tasks.md") or p.endswith("STATUS.md")),
        "",
    )
    if not source or not (root / source).is_file():
        report.warnf("检查 5：地图里没有状态源（tasks.md / STATUS.md），进度无法机检")
        return
    text = (root / source).read_text(encoding="utf-8-sig")
    rows = status_rows(text)
    if not rows:
        report.warnf(f"检查 5：{source} 里没解析到状态表，进度无法机检")
        return

    bad = 0
    for cells in rows:
        item, status, evidence = cells[0].replace("`", ""), cells[6], cells[7]
        if not status.startswith(STATUS_PREFIXES):
            report.bad(f"检查 5：状态值非法「{status}」（{item}）；只允许 {'/'.join(STATUS_PREFIXES)}")
            bad += 1
            continue
        if status.startswith(EVIDENCE_REQUIRED_PREFIXES) and evidence in EMPTY_EVIDENCE:
            report.bad(f"检查 5：{item} 标了「{status}」但证据列（子编号）为空")
            bad += 1
    if bad == 0:
        report.ok(f"检查 5：状态枚举与证据列合规（{source}，{len(rows)} 行）")


def check_links(report: Report, root: Path, files: list[str]) -> None:
    """只查被地图覆盖的文档——豁免区（skills / .specify / archive）不参与路由。"""
    dead: list[str] = []
    for rel in files:
        if rel.startswith(LINK_SKIP_PREFIXES):
            continue
        file_path = root / rel
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for target in LINK_RE.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#", "/")) or "%" in target:
                continue
            target = target.split("#", 1)[0].strip()
            if not target:
                continue
            if not (file_path.parent / target).exists() and not (root / target).exists():
                dead.append(f"{rel} → {target}")
    if not dead:
        report.ok("检查 6：文档内相对链接均可解析")
        return
    for item in dead[:5]:
        report.warnf(f"检查 6：死链 {item}")
    if len(dead) > 5:
        report.warnf(f"检查 6：另有 {len(dead) - 5} 处死链（只列前 5 处）")


def check_forbidden_terms(report: Report, root: Path, files: list[str]) -> None:
    """已失效术语是否回流到活文档；ADR 正文与归档件保留历史原貌，不查。"""
    hits: list[str] = []
    for rel in files:
        if rel.startswith(FORBIDDEN_SKIP_PREFIXES):
            continue
        try:
            lines = (root / rel).read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, start=1):
            if any(token in line for token in FORBIDDEN_SKIP_TOKENS):
                continue
            for term, hint in FORBIDDEN_TERMS.items():
                if term in line:
                    hits.append(f"{rel}:{lineno} 提及 {term}（{hint}）")
    if not hits:
        report.ok("检查 7：活文档无已失效术语回流")
        return
    for item in hits[:5]:
        report.warnf(f"检查 7：{item}")
    if len(hits) > 5:
        report.warnf(f"检查 7：另有 {len(hits) - 5} 处（只列前 5 处）")


def main(argv: list[str]) -> int:
    root = REPO_ROOT
    strict = "--strict" in argv
    if "--root" in argv:
        idx = argv.index("--root")
        if idx + 1 >= len(argv):
            print("--root 需要一个目录参数", file=sys.stderr)
            return 64
        root = Path(argv[idx + 1]).resolve()
    if not root.is_dir():
        print(f"目录不存在：{root}", file=sys.stderr)
        return 64

    agents = root / "AGENTS.md"
    if not agents.is_file():
        print(f"找不到 AGENTS.md：{agents}", file=sys.stderr)
        print("本脚本只认 AGENTS.md 作为 L0；没有就先建立入口。", file=sys.stderr)
        return 64

    print(f"▶ doc-check | 根目录：{root}")
    text = agents.read_text(encoding="utf-8-sig")
    paths = parse_map(text)
    patterns = parse_excludes(text)

    report = Report()
    check_map_rows(report, root, paths)
    if paths:
        all_md = collect_markdown(root)
        covered = [rel for rel in all_md if any(covers(rel, p) for p in paths if "*" not in p)]
        check_coverage(report, all_md, paths, patterns)
        check_meta_headers(report, root, paths)
        check_status(report, root, paths)
        check_links(report, root, covered)
        check_forbidden_terms(report, root, covered)

    print("")
    print(f"—— 汇总：{report.fail} 项 FAIL，{report.warn} 项 WARN ——")
    if report.fail:
        return 1
    if strict and report.warn:
        print("（--strict：WARN 也算失败）")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
