"""黄金快照裁剪器 — 从生产库（只读）裁剪指定日期区间的 tca_route_summary
到独立快照文件，供黄金样本基线生成/回归使用。

用法（仓库根执行）：
    python CostView/scripts/make_golden_snapshot.py \
        --start 20260901 --end 20260904 \
        --out _tmp/golden-snapshot

背景：生产 fill_bdib.db 达 GB 级，整库复制成本高且内容随每日更新漂移；
黄金基线只需要 tca_route_summary 的**冻结**行集。快照放 `_tmp/`
（.gitignore 覆盖，数据不入库），基线 JSON 人工 review 后入库。

只读安全：源库以 mode=ro URI 打开，绝不写生产数据（G0 红线）。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from data_access.config import Config  # noqa: E402


def make_snapshot(source_db: Path, out_dir: Path, start: str, end: str) -> int:
    """从源库只读裁剪 tca_route_summary 到 out_dir/fill_bdib.db。"""
    out_db = out_dir / "fill_bdib.db"
    out_dir.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    # URI 解析需主连接以 uri=True 打开，ATTACH 的 mode=ro 才会生效
    # （pathname2url 处理 Windows 盘符/空格/中文路径，与 data_access 同款）
    from urllib.request import pathname2url
    src_uri = "file:" + pathname2url(str(source_db)) + "?mode=ro"

    dst = sqlite3.connect(out_db, uri=True)
    try:
        # ATTACH 只读源库，跨库 INSERT ... SELECT 完成裁剪
        dst.execute(f"ATTACH DATABASE '{src_uri}' AS src_main")

        schema_row = dst.execute(
            "SELECT sql FROM src_main.sqlite_master "
            "WHERE type='table' AND name = ?",
            (Config.TCA_ROUTE_SUMMARY_TABLE,),
        ).fetchone()
        if schema_row is None:
            raise SystemExit(
                f"[ERROR] 源库缺少 {Config.TCA_ROUTE_SUMMARY_TABLE} 表: {source_db}"
            )
        dst.execute(schema_row[0])

        cur = dst.execute(
            f"""
            INSERT INTO main.{Config.TCA_ROUTE_SUMMARY_TABLE}
            SELECT * FROM src_main.{Config.TCA_ROUTE_SUMMARY_TABLE}
            WHERE order_as_of_date >= ? AND order_as_of_date <= ?
            """,
            (start, end),
        )
        dst.commit()
        count = cur.rowcount
        dst.execute("DETACH DATABASE src_main")
        return int(count)
    finally:
        dst.close()


def main() -> int:
    # Windows 控制台 cp1252 打印中文会 UnicodeEncodeError，强制 UTF-8
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            try:
                _s.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    parser = argparse.ArgumentParser(description="黄金快照裁剪器")
    parser.add_argument("--source", type=Path, default=Config.FILL_BDIB_DB,
                        help="源 fill_bdib.db（只读，默认生产路径）")
    parser.add_argument("--start", required=True, help="起始日 YYYYMMDD")
    parser.add_argument("--end", required=True, help="结束日 YYYYMMDD")
    parser.add_argument("--out", type=Path, default=Path("_tmp/golden-snapshot"),
                        help="快照输出目录")
    args = parser.parse_args()

    count = make_snapshot(args.source, args.out, args.start, args.end)
    print(f"[OK] 快照写入 {args.out / 'fill_bdib.db'} ({count} rows, {args.start}~{args.end})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
