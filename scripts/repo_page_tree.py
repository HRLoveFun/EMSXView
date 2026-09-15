#!/usr/bin/env python3
"""生成远端仓库的目录（tree 页面）网页链接。

用法：
    python scripts/repo_page_tree.py                 # 仅输出目录页面
    python scripts/repo_page_tree.py --with-files    # 同时输出文件（blob）页面
    python scripts/repo_page_tree.py --branch main   # 指定分支/标签
    python scripts/repo_page_tree.py --output pages.txt  # 写入文件而非打印
"""
import argparse
import subprocess
import sys
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


def repo_tree_urls(with_files: bool = False, branch: str | None = None,
                   root: str | None = None, subdir: str | None = None) -> list[str]:
    """生成仓库所有目录（tree 页面）的网页 URL。

    subdir 非空时仅输出该子目录子树的页面。
    """
    base = normalize_web_base(get_remote_url())
    branch = branch or get_default_branch()
    files = subprocess.check_output(
        ["git", "ls-files"], cwd=root, text=True
    ).splitlines()

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
    args = parser.parse_args()

    urls = repo_tree_urls(with_files=args.with_files, branch=args.branch,
                          subdir=args.subdir)
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
