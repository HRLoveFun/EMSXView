"""清理 processed_fills.db 中分区迁移残留的空壳表。

背景（2026-08-26 事故 A3，见 docs/spec/pipeline-resilience.md §1）：
Phase B 分区迁移将 route_registry / ticker_repository 等表迁至独立分区库，
但 processed_fills.db 中残留了 0 行空壳表。SqliteFillReadRepository._conn_for
的 B4 自动检测以「表是否存在」为路由判据，导致读取被路由到空壳表
（如 get_ticker_exchange_map 返回 {}），S5 BDIB 阶段静默短路、raw_bdib 停更。

安全闸（dry-run 默认，--apply 才执行 DROP）：
1. 候选表仅限 DataPipeline.storage.repositories.fills._PARTITION_DB_MAP 登记的分区表
2. legacy 表必须存在且 COUNT(*) = 0（有任何一行即拒绝处理）
3. 分区库对应表必须存在且 COUNT(*) > 0（迁移未完成即拒绝处理）
4. 表结构 DDL 导出至 manifest.json（可据此重建，具备回滚能力）

用法：
    python scripts/ops/drop_partition_shell_tables.py            # dry-run
    python scripts/ops/drop_partition_shell_tables.py --apply    # 执行 DROP
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 cp1252，中文输出会触发 UnicodeEncodeError，强制 UTF-8
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(
        sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )
    sys.stderr = io.TextIOWrapper(
        sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
    )

# 脚本方式运行时补充项目根到 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from DataPipeline.storage.connection import ConnectionManager
from DataPipeline.storage.repositories.fills import _PARTITION_DB_MAP

logger = logging.getLogger("drop_partition_shell_tables")

MANIFEST_DIR = _PROJECT_ROOT / "logs" / "pipeline"


def _table_state(conn, table: str) -> tuple[bool, int]:
    """返回 (表是否存在, 行数)。"""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None
    if not exists:
        return False, 0
    rows = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    return True, int(rows)


def scan_shell_tables(mgr: ConnectionManager) -> list[dict]:
    """扫描全部登记分区表在 legacy/分区库两侧的状态，返回可清理项。"""
    candidates: list[dict] = []
    for table in sorted(_PARTITION_DB_MAP):
        target_db = _PARTITION_DB_MAP[table]
        with mgr.get_admin_connection("processed_fills") as conn:
            legacy_exists, legacy_rows = _table_state(conn, table)
            ddl = (
                conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                ).fetchone()[0]
                if legacy_exists
                else None
            )
        with mgr.get_admin_connection(target_db) as conn:
            part_exists, part_rows = _table_state(conn, table)

        entry = {
            "table": table,
            "target_db": target_db,
            "legacy_exists": legacy_exists,
            "legacy_rows": legacy_rows,
            "partition_rows": part_rows,
            "ddl": ddl,
        }
        # 三道闸：legacy 存在 + legacy 空 + 分区库有数据
        droppable = legacy_exists and legacy_rows == 0 and part_rows > 0
        entry["droppable"] = droppable
        if not droppable and legacy_exists:
            entry["skip_reason"] = (
                f"legacy_rows={legacy_rows}, partition_rows={part_rows}"
                " — 不满足清理条件"
            )
        candidates.append(entry)
    return candidates


def apply_drop(mgr: ConnectionManager, droppables: list[dict]) -> None:
    """在同一事务内 DROP 全部空壳表（全部通过安全闸才执行）。"""
    with mgr.get_admin_connection("processed_fills") as conn:
        try:
            for entry in droppables:
                conn.execute(f'DROP TABLE "{entry["table"]}"')
                logger.info("已 DROP: %s", entry["table"])
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def write_manifest(candidates: list[dict], applied: bool) -> Path:
    """写入审计 manifest（含 DDL，可重建回滚）。"""
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = MANIFEST_DIR / f"drop_partition_shell_tables_{ts}.json"
    path.write_text(
        json.dumps(
            {"applied": applied, "timestamp": ts, "tables": candidates},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="清理 processed_fills.db 分区迁移残留空壳表",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="实际执行 DROP（默认 dry-run 仅扫描）",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    mgr = ConnectionManager()
    candidates = scan_shell_tables(mgr)
    droppables = [c for c in candidates if c["droppable"]]
    skipped = [c for c in candidates if c.get("skip_reason")]

    print(f"\n扫描完成：候选 {len(candidates)} 张，可清理 {len(droppables)} 张\n")
    for c in candidates:
        status = "可清理" if c["droppable"] else ("跳过" if c.get("skip_reason") else "不存在")
        print(
            f"  [{status}] {c['table']:24s} legacy={c['legacy_rows']} 行, "
            f"{c['target_db']}={c['partition_rows']} 行"
        )

    if skipped:
        print("\n以下表不满足安全闸条件，已排除：")
        for c in skipped:
            print(f"  - {c['table']}: {c['skip_reason']}")

    if not args.apply:
        manifest = write_manifest(candidates, applied=False)
        print(f"\n[dry-run] 未做任何变更。manifest: {manifest}")
        return 0

    if not droppables:
        print("\n无满足条件的空壳表，无需执行。")
        return 0

    apply_drop(mgr, droppables)
    manifest = write_manifest(candidates, applied=True)
    print(f"\n[apply] 已 DROP {len(droppables)} 张空壳表。manifest: {manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
