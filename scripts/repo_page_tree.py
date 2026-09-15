#!/usr/bin/env python3
"""生成远端仓库的目录（tree 页面）网页链接。

用法：
    python scripts/repo_page_tree.py                 # 仅输出目录页面
    python scripts/repo_page_tree.py --with-files    # 同时输出文件（blob）页面
    python scripts/repo_page_tree.py --branch main   # 指定分支/标签
    python scripts/repo_page_tree.py --output pages.txt  # 写入文件而非打印
    python scripts/repo_page_tree.py --since 2026-01-01          # 仅 2026 年起更新的文件
    python scripts/repo_page_tree.py --since "3 months ago" --with-files  # 近 3 个月更新的文件+页面
    python scripts/repo_page_tree.py --until 2026-06-01 --subdir CostView  # CostView 下 6 月前更新的
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import quote


def get_remote_url(remote: str = "origin") -> str:
    """获取远端仓库地址（兼容 SSH / HTTPS 两种格式）。"""
    try:
        return subprocess.check_output(
            ["git", "remote", "get-url", remote], text=True
        ).strip()
    except subprocess.CalledProcessError:
        sys.exit("无法获取远端地址，请确认当前目录位于 git 仓库内且已配置 origin。")


def normalize_web_base(url: str) -> str:
    """把 git 地址归一化为网页 base URL。

    git@github.com:owner/repo.git -> https://github.com/owner/repo
    https://github.com/owner/repo.git -> https://github.com/owner/repo
    """
    url = url.removesuffix(".git")
    if url.startswith("git@"):
        host, path = url[4:].split(":", 1)
        return f"https://{host}/{path}"
    return url


def get_default_branch() -> str:
    """获取当前默认分支名；获取失败时回落到 main。"""
    try:
        return subprocess.check_output(
            ["git", "symbolic-ref", "--short", "HEAD"], text=True
        ).strip()
    except subprocess.CalledProcessError:
        return "main"


def get_file_mtimes(ref: str = "HEAD") -> dict[str, float]:
    """返回每个被跟踪文件最后一次提交的 Unix 时间戳。

    利用 git log 倒序输出，文件首次出现即为其最新提交时间。
    """
    try:
        out = subprocess.check_output(
            ["git", "log", ref, "--format=COMMIT\t%ct",
             "--name-only", "--no-merges"], text=True
        )
    except subprocess.CalledProcessError:
        return {}
    mtimes: dict[str, float] = {}
    current_ts: float | None = None
    for line in out.splitlines():
        if line.startswith("COMMIT\t"):
            try:
                current_ts = float(line.split("\t", 1)[1])
            except ValueError:
                current_ts = None
        elif line.strip() and current_ts is not None:
            mtimes.setdefault(line, current_ts)  # 仅记录首次（最新）提交时间
    return mtimes


def resolve_date(s: str) -> float:
    """把日期参数解析为 Unix 时间戳。

    支持：纯数字（视为 Unix 时间戳）、ISO 日期（如 2026-01-01）、
    git 相对写法（如 "3 months ago"）。
    """
    if re.fullmatch(r"\d+", s):
        return float(s)
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        pass
    # 交给 git 解析相对/绝对日期，取该日期前最近一次提交的时间戳作近似边界
    try:
        h = subprocess.check_output(
            ["git", "rev-list", "-n", "1", f"--before={s}", "HEAD"], text=True
        ).strip()
        if h:
            return float(subprocess.check_output(
                ["git", "show", "-s", "--format=%ct", h], text=True).strip())
    except subprocess.CalledProcessError:
        pass
    sys.exit(f"无法解析日期参数：{s}")


def repo_tree_urls(with_files: bool = False, branch: str | None = None,
                   root: str | None = None, subdir: str | None = None,
                   since: str | None = None,
                   until: str | None = None) -> list[str]:
    """生成仓库所有目录（tree 页面）的网页 URL。

    subdir 非空时仅输出该子目录子树的页面；
    since/until 非空时仅保留最后提交时间在时间区间内的文件。
    """
    base = normalize_web_base(get_remote_url())
    branch = branch or get_default_branch()
    files = subprocess.check_output(
        ["git", "ls-files"], cwd=root, text=True
    ).splitlines()

    # 按更新时间（最后提交时间）过滤文件
    if since or until:
        since_ts = resolve_date(since) if since else None
        until_ts = resolve_date(until) if until else None
        mtimes = get_file_mtimes(branch or "HEAD")
        files = [
            f for f in files
            if (since_ts is None or mtimes.get(f, 0.0) >= since_ts)
            and (until_ts is None or mtimes.get(f, 0.0) <= until_ts)
        ]

    # 指定子目录时先过滤文件，并把起点设为该子目录的 tree 页面
    if subdir:
        subdir = subdir.strip("/")
        prefix = subdir + "/"
        files = [f for f in files if f == subdir or f.startswith(prefix)]
        urls: set[str] = {f"{base}/tree/{branch}/{quote(subdir)}"}
    else:
        urls: set[str] = {f"{base}/tree/{branch}"}

    for f in files:
        if with_files:
            urls.add(f"{base}/blob/{branch}/{quote(f)}")
        # 由文件的父目录链推导出所有 tree 页面（空目录不出现）
        p = PurePosixPath(f)
        for parent in p.parents:
            if str(parent) == ".":
                continue
            urls.add(f"{base}/tree/{branch}/{quote(str(parent))}")
    return sorted(urls)


def main() -> None:
    # Windows 控制台默认 cp1252，强制 UTF-8 避免中文/特殊字符输出报错
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="生成远端仓库目录（tree）网页链接")
    parser.add_argument("--with-files", action="store_true",
                        help="同时输出文件（blob）页面")
    parser.add_argument("--branch", default=None,
                        help="指定分支/标签，默认当前分支")
    parser.add_argument("--output", default=None,
                        help="写入文件而非打印到对话")
    parser.add_argument("--subdir", default=None,
                        help="仅输出指定子目录子树的页面，如 CostView")
    parser.add_argument("--since", default=None,
                        help="仅保留最后提交时间 >= 该日期的文件，如 2026-01-01 或 '3 months ago'")
    parser.add_argument("--until", default=None,
                        help="仅保留最后提交时间 <= 该日期的文件，如 2026-06-01")
    args = parser.parse_args()

    urls = repo_tree_urls(with_files=args.with_files, branch=args.branch,
                          subdir=args.subdir, since=args.since, until=args.until)
    text = "\n".join(urls)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"已写入 {args.output}（共 {len(urls)} 条）")
    else:
        print(text)
        print(f"\n# 共 {len(urls)} 条")


if __name__ == "__main__":
    main()
