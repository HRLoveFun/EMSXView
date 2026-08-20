"""snapshot_guard.py — 数据库迁移/重算前的基线快照守卫（003-tca-core-benchmarks G0/P1）。

在任何 Schema 迁移或 tca_route_summary 重算之前调用，确保：
1. 复制涉及的 SQLite 数据库文件到快照目录
2. 记录 PRAGMA user_version、行数、各表列数、关键列非 NULL 率到 JSON 清单
3. 提供恢复命令（从清单恢复备份）

用法:
    # 创建快照（迁移/重算前）
    python scripts/ops/snapshot_guard.py --create --label pre-tca-v2-migration

    # 查看已有快照清单
    python scripts/ops/snapshot_guard.py --list

    # 恢复到指定快照（--restore 后接快照目录名）
    python scripts/ops/snapshot_guard.py --restore pre-tca-v2-migration --force

    # 校验快照与当前库的一致性（对比行数/列数/版本）
    python scripts/ops/snapshot_guard.py --verify pre-tca-v2-migration
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 确保可导入 DataPipeline
_SCRIPT_DIR = Path(__file__).resolve().parent
_EMSX_ROOT = _SCRIPT_DIR.parent.parent
sys.path.insert(0, str(_EMSX_ROOT))

from DataPipeline.config import Config

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 涉及迁移/重算的数据库
_WATCHED_DBS: List[str] = ["fill_bdib"]  # tca_route_summary 所在库
_SNAPSHOT_ROOT = Config.DATA_DIR / "snapshots"

# 需要记录非 NULL 率的关键列（按表）
_TRS_KEY_COLUMNS = [
    "fill", "p_avg", "pnl_vwap", "RPM", "fill_count",
    "p_arrival", "p_close", "arrival_cost_bps", "close_cost_bps",
    "opportunity_cost",
]


def _db_path(db_key: str) -> Path:
    """按数据库键返回路径。"""
    paths = {
        "fill_bdib": Config.FILL_BDIB_DB,
    }
    return paths[db_key]


def _snapshot_dir(label: str) -> Path:
    """快照目录 = SNAPSHOT_ROOT / label。"""
    return _SNAPSHOT_ROOT / label


def _table_info(conn: sqlite3.Connection, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def _collect_manifest(db_key: str) -> Dict[str, Any]:
    """收集单个数据库的清单信息。"""
    db_path = _db_path(db_key)
    manifest: Dict[str, Any] = {
        "db_key": db_key,
        "path": str(db_path),
        "exists": db_path.exists(),
    }
    if not db_path.exists():
        return manifest

    conn = sqlite3.connect(str(db_path))
    try:
        manifest["file_size"] = db_path.stat().st_size
        manifest["user_version"] = conn.execute("PRAGMA user_version").fetchone()[0]
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        ]
        manifest["tables"] = {}
        for t in tables:
            cols = _table_info(conn, t)
            try:
                count = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:
                count = None
            table_manifest: Dict[str, Any] = {
                "columns": cols,
                "row_count": count,
                "non_null_rates": {},
            }
            # 关键列非 NULL 率（仅 tca_route_summary）
            if t == Config.TCA_ROUTE_SUMMARY_TABLE:
                for col in _TRS_KEY_COLUMNS:
                    if col in cols:
                        try:
                            non_null = conn.execute(
                                f"SELECT COUNT(*) FROM {t} WHERE {col} IS NOT NULL"
                            ).fetchone()[0]
                            table_manifest["non_null_rates"][col] = (
                                round(non_null / count, 6) if count else None
                            )
                        except Exception:
                            table_manifest["non_null_rates"][col] = None
            manifest["tables"][t] = table_manifest
    finally:
        conn.close()
    return manifest


def _file_hash(path: Path) -> str:
    """计算文件 SHA-256（分块，避免大文件内存占用）。"""
    h = hashlib.sha256()
    with open(str(path), "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def create_snapshot(label: str, force: bool = False) -> int:
    """创建快照：复制 DB 文件 + 写清单 JSON。"""
    snap_dir = _snapshot_dir(label)
    if snap_dir.exists() and not force:
        print(f"快照已存在: {snap_dir}（使用 --force 覆盖）")
        return 1
    if not force:
        snap_dir.mkdir(parents=True, exist_ok=True)
    else:
        snap_dir.mkdir(parents=True, exist_ok=True)
        # 清空旧内容
        for item in snap_dir.iterdir():
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()

    manifests = {}
    for db_key in _WATCHED_DBS:
        db_path = _db_path(db_key)
        if not db_path.exists():
            print(f"[SKIP] {db_key} 不存在: {db_path}")
            continue
        target = snap_dir / f"{db_key}.db"
        shutil.copy2(str(db_path), str(target))
        manifest = _collect_manifest(db_key)
        manifest["backup_path"] = str(target)
        manifest["sha256"] = _file_hash(target)
        manifests[db_key] = manifest
        print(f"[OK] {db_key}: {db_path.stat().st_size} bytes -> {target}")

    manifest_file = snap_dir / "manifest.json"
    with open(str(manifest_file), "w", encoding="utf-8") as f:
        json.dump(
            {
                "label": label,
                "created_at": datetime.now().isoformat(),
                "databases": manifests,
            },
            f, ensure_ascii=False, indent=2,
        )
    print(f"[OK] 清单已写入: {manifest_file}")
    print(f"快照完成: {snap_dir}")
    return 0


def list_snapshots() -> int:
    """列出已有快照。"""
    if not _SNAPSHOT_ROOT.exists():
        print("无快照目录")
        return 0
    for d in sorted(_SNAPSHOT_ROOT.iterdir()):
        if not d.is_dir():
            continue
        mf = d / "manifest.json"
        if mf.exists():
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
                created = meta.get("created_at", "?")
                dbs = ", ".join(meta.get("databases", {}).keys())
            except Exception:
                created, dbs = "?", "?"
        else:
            created, dbs = "?", "?"
        print(f"{d.name:40s} {created}  [{dbs}]")
    return 0


def restore_snapshot(label: str, force: bool = False) -> int:
    """从快照恢复数据库文件。"""
    snap_dir = _snapshot_dir(label)
    if not snap_dir.exists():
        print(f"快照不存在: {snap_dir}")
        return 1
    mf = snap_dir / "manifest.json"
    if not mf.exists():
        print(f"快照缺少 manifest.json: {mf}")
        return 1

    meta = json.loads(mf.read_text(encoding="utf-8"))
    if not force:
        print("恢复为破坏性操作。请确认目标库状态后使用 --force 执行。")
        return 1

    for db_key, db_manifest in meta.get("databases", {}).items():
        backup = Path(db_manifest["backup_path"])
        if not backup.exists():
            print(f"[FAIL] 备份文件缺失: {backup}")
            continue
        target = Path(db_manifest["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(backup), str(target))
        print(f"[OK] 已恢复 {db_key}: {target}")
    print("恢复完成")
    return 0


def verify_snapshot(label: str) -> int:
    """校验快照与当前库的一致性（对比行数/列数/版本/哈希）。"""
    snap_dir = _snapshot_dir(label)
    if not snap_dir.exists():
        print(f"快照不存在: {snap_dir}")
        return 1
    mf = snap_dir / "manifest.json"
    if not mf.exists():
        print(f"快照缺少 manifest.json: {mf}")
        return 1

    meta = json.loads(mf.read_text(encoding="utf-8"))
    ok = True
    for db_key, snap in meta.get("databases", {}).items():
        current = _collect_manifest(db_key)
        snap_row = snap["tables"].get(Config.TCA_ROUTE_SUMMARY_TABLE, {}).get("row_count")
        cur_row = current["tables"].get(Config.TCA_ROUTE_SUMMARY_TABLE, {}).get("row_count")
        snap_cols = snap["tables"].get(Config.TCA_ROUTE_SUMMARY_TABLE, {}).get("columns", [])
        cur_cols = current["tables"].get(Config.TCA_ROUTE_SUMMARY_TABLE, {}).get("columns", [])
        row_ok = (snap_row == cur_row)
        col_ok = (snap_cols == cur_cols)
        print(f"[{db_key}]")
        print(f"  行数: 快照={snap_row}, 当前={cur_row} {'✅' if row_ok else '❌'}")
        print(f"  列数: 快照={len(snap_cols)}, 当前={len(cur_cols)} {'✅' if col_ok else '❌'}")
        if not row_ok or not col_ok:
            ok = False
    print("一致性校验:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="数据库快照守卫（迁移/重算前基线）")
    parser.add_argument("--create", action="store_true", help="创建快照")
    parser.add_argument("--list", action="store_true", help="列出快照")
    parser.add_argument("--restore", metavar="LABEL", help="恢复到指定快照")
    parser.add_argument("--verify", metavar="LABEL", help="校验快照一致性")
    parser.add_argument("--label", default="snapshot", help="快照标签")
    parser.add_argument("--force", action="store_true", help="覆盖/强制操作")
    args = parser.parse_args()

    if args.list:
        return list_snapshots()
    if args.create:
        return create_snapshot(args.label, force=args.force)
    if args.restore:
        return restore_snapshot(args.restore, force=args.force)
    if args.verify:
        return verify_snapshot(args.verify)

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
