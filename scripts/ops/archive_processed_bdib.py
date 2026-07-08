"""归档 processed_bdib.db 孤儿文件。

processed_bdib.db 是早期 fill_bdib 曾命名 processed_bdib 时的遗留产物。
当前 Config 中无此 DB 注册，全项目无代码写入路径。
最后修改时间 2026-04-09，与 fill_bdib 表 schema 完全一致。

已于 2026-07-07 直接删除（用户选择不归档）。

脚本功能（保留用于未来类似场景的引用检查）：
1. 扫描全项目确认无代码引用 processed_bdib.db（排除 processed_raw_bdib）
2. --dry-run: 输出引用检查结果 + 文件信息
3. --apply: 移动到 CostView/data/_archive/ 目录（保留审计痕迹）
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from DataPipeline.config import Config

logger = logging.getLogger(__name__)


def _find_processed_bdib_references(src_root: Path) -> List[Path]:
    """扫描全项目，查找引用 processed_bdib 但非 processed_raw_bdib 的文件。

    返回匹配到的文件路径列表。排除：
    - processed_raw_bdib (是另一个独立的 DB)
    - 文档文件 (.md)
    - 本脚本自身
    - _archive/ 目录
    """
    results: List[Path] = []
    # 匹配 processed_bdib 但后面不跟 _raw 或 raw
    pattern = re.compile(r"(?<!_)processed_bdib\b(?!_)")

    for py_file in src_root.rglob("*.py"):
        # 跳过本脚本和归档目录
        if "archive_processed_bdib" in str(py_file):
            continue
        if "_archive" in py_file.parts:
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="ignore")
            if pattern.search(content):
                # 排除 processed_raw_bdib 上下文
                if "processed_raw_bdib" in content:
                    continue
                results.append(py_file)
        except Exception as e:
            logger.debug("跳过文件 %s: %s", py_file, e)

    return results


def _get_file_info(db_path: Path) -> dict:
    """获取文件信息。"""
    stat = db_path.stat()
    return {
        "path": str(db_path),
        "size_mb": stat.st_size / (1024 * 1024),
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        "exists": db_path.exists(),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="归档 processed_bdib.db 孤儿文件",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅检查引用和文件信息，不执行归档",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="执行归档（移动到 _archive/ 目录）",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format=Config.LOG_FORMAT)

    src_root = Config._PROJECT_ROOT

    # 1. 引用检查
    logger.info("扫描代码引用...")
    refs = _find_processed_bdib_references(src_root)
    if refs:
        logger.warning("发现 %d 处 processed_bdib 引用:", len(refs))
        for f in refs:
            logger.warning("  %s", f.relative_to(src_root))
    else:
        logger.info("代码引用检查通过：未发现 processed_bdib 引用（排除 processed_raw_bdib）")

    # 2. 文件信息
    db_path = src_root / "CostView" / "data" / "processed_bdib.db"
    info = _get_file_info(db_path)
    logger.info("文件信息: %s", info)

    if not info["exists"]:
        logger.info("processed_bdib.db 不存在，无需归档")
        return 0

    if args.dry_run:
        logger.info("DRY-RUN 模式: 将归档 %s (%.2f MB) 到 _archive/", info["path"], info["size_mb"])
        return 0

    if not args.apply:
        logger.info("请使用 --apply 确认归档，或 --dry-run 预览")
        return 0

    # 3. 归档
    archive_dir = src_root / "CostView" / "data" / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_path = archive_dir / f"processed_bdib.db.{ts}"

    shutil.move(str(db_path), str(target_path))
    logger.info("已归档: %s -> %s", info["path"], target_path)

    # 验证
    if not target_path.exists():
        logger.error("归档失败: 目标文件不存在 %s", target_path)
        return 1
    if db_path.exists():
        logger.warning("归档后源文件仍存在（跨分区移动降级为复制？）")
    else:
        logger.info("归档成功: %.2f MB 已移动到 _archive/", info["size_mb"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
