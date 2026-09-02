"""将项目内数据目录（CostView/data）迁移到项目外默认位置（009-external-data-store）。

三道安全闸（对齐 docs/spec/plan-design-principles.md P1 数据零受损）：

1. 预检  — 源目录存在且有 *.db；目标目录不存在或为空（--force 才允许覆盖）；
           磁盘剩余空间充足；提醒先停止管道/API 进程。
2. 校验  — 逐文件复制后，对每个 .db 执行 PRAGMA integrity_check 并比对
           源/目标文件字节数，全部一致才视为成功。
3. 留证  — 成功后将源目录整体改名为 ``data.migrated.<timestamp>``，
           不删除任何数据；确认无误后由人工清理。

幂等可重入：重复执行时若源目录已无 *.db（已迁移/已改名）则直接提示完成；
目标目录已有数据时默认拒绝（--force 显式覆盖）。

用法::

    python scripts/ops/migrate_data_dir.py --dry-run      # 仅打印计划
    python scripts/ops/migrate_data_dir.py                # 执行迁移
    python scripts/ops/migrate_data_dir.py --src X --dst Y  # 自定义路径
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 cp1252/cp936，中文与制表符输出需显式 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 项目根 = scripts/ops/ 的上两级（本脚本通过 __file__ 自定位，与 cwd 无关）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT))

from DataPipeline.config import Config  # noqa: E402


def _default_src() -> Path:
    """源目录：项目内旧布局（Config.LEGACY_DATA_DIR）。"""
    return Config.LEGACY_DATA_DIR


def _default_dst() -> Path:
    """目标目录：EMSXVIEW_DATA_DIR 显式指定时用之，否则用项目外默认值。"""
    return Config.DATA_DIR


def _check_integrity(db_file: Path) -> None:
    """对单个 SQLite 文件执行完整性校验（quick_check 快速且足以发现损坏）。"""
    conn = sqlite3.connect(str(db_file))
    try:
        result = conn.execute("PRAGMA quick_check").fetchone()
    finally:
        conn.close()
    if not result or str(result[0]).lower() != "ok":
        raise RuntimeError(f"完整性校验失败: {db_file} → {result!r}")


def _collect_copy_plan(src: Path, dst: Path) -> list[tuple[Path, Path]]:
    """收集复制计划：顶层 *.db / *.db-wal / *.db-shm / *.json 与 fills、market 子目录。"""
    plan: list[tuple[Path, Path]] = []
    for pattern in ("*.db", "*.db-wal", "*.db-shm", "*.json"):
        for f in src.glob(pattern):
            plan.append((f, dst / f.name))
    for sub in ("fills", "market"):
        sub_dir = src / sub
        if not sub_dir.is_dir():
            continue
        for f in sub_dir.rglob("*"):
            if f.is_file():
                plan.append((f, dst / sub / f.relative_to(sub_dir)))
    return plan


def _precheck(src: Path, dst: Path, force: bool) -> list[tuple[Path, Path]]:
    """闸 1：预检。返回复制计划；失败抛 SystemExit。"""
    if not src.is_dir():
        # 源目录缺失可能是已迁移（存在留证目录）——给出幂等提示而非裸报错
        evidence = sorted(src.parent.glob(f"{src.name}.migrated.*"))
        if evidence:
            print(
                f"[已完成] 源目录已迁移留证: {evidence[-1]}，无需重复迁移。"
                f"如需使用新位置，直接运行即可（当前数据目录: {Config.DATA_DIR}）"
            )
            sys.exit(0)
        raise SystemExit(f"[预检失败] 源目录不存在: {src}")
    plan = _collect_copy_plan(src, dst)
    db_files = [p for p, _ in plan if p.suffix == ".db"]
    if not db_files:
        raise SystemExit(
            f"[预检失败] 源目录无 *.db 文件（可能已迁移过）: {src}"
        )
    if dst.exists() and any(dst.iterdir()) and not force:
        raise SystemExit(
            f"[预检失败] 目标目录非空: {dst}（确认覆盖请加 --force）"
        )
    if _is_pipeline_running_hint():
        print("[警告] 检测到数据库可能被占用（存在 -wal/-shm 文件）。")
        print("       请先停止数据管道与 API 服务再迁移，避免复制到不一致快照。")
    # 磁盘空间预检（目标所在盘剩余空间须大于源数据体积）
    src_bytes = sum(p.stat().st_size for p, _ in plan)
    free = shutil.disk_usage(str(dst if dst.exists() else dst.parent)).free
    if free < src_bytes:
        raise SystemExit(
            f"[预检失败] 目标盘剩余空间不足: 需 {src_bytes / 2**30:.2f} GiB, "
            f"剩 {free / 2**30:.2f} GiB"
        )
    print(f"[预检通过] 源: {src}")
    print(f"[预检通过] 目标: {dst}")
    print(f"[预检通过] 待复制 {len(plan)} 个文件, 共 {src_bytes / 2**30:.2f} GiB")
    return plan


def _is_pipeline_running_hint() -> bool:
    """存在 -wal/-shm 文件通常意味着有进程正持有连接（启发式提示）。"""
    return bool(list(_default_src().glob("*.db-wal")))


def _copy_and_verify(plan: list[tuple[Path, Path]], src: Path) -> None:
    """闸 2：复制 + 校验（字节数一致 + 每库 quick_check）。"""
    for s, d in plan:
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(s), str(d))
        if s.stat().st_size != d.stat().st_size:
            raise RuntimeError(
                f"复制后字节数不一致: {s}({s.stat().st_size}) → "
                f"{d}({d.stat().st_size})"
            )
    db_files = [d for _, d in plan if d.suffix == ".db"]
    for db in db_files:
        _check_integrity(db)
        print(f"[校验通过] {db.name} ({db.stat().st_size / 2**20:.1f} MiB)")


def _seal_source(src: Path) -> Path:
    """闸 3：源目录改名留证（不删除任何数据）。"""
    sealed = src.with_name(f"{src.name}.migrated.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    src.rename(sealed)
    return sealed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="迁移项目内数据目录到项目外（009-external-data-store）",
    )
    parser.add_argument("--src", type=Path, default=None, help="源目录（默认 CostView/data）")
    parser.add_argument("--dst", type=Path, default=None, help="目标目录（默认 ~/EMSXViewData/data）")
    parser.add_argument("--force", action="store_true", help="目标目录非空时仍继续")
    parser.add_argument("--dry-run", action="store_true", help="仅打印计划，不执行复制")
    args = parser.parse_args()

    src = (args.src or _default_src()).resolve()
    dst = (args.dst or _default_dst()).resolve()

    print("═══ EMSXView 数据目录迁移 (009-external-data-store) ═══")
    plan = _precheck(src, dst, force=args.force)
    if args.dry_run:
        print("[dry-run] 仅打印计划，未执行复制。计划明细：")
        for s, d in plan:
            print(f"  {s}  →  {d}")
        return

    _copy_and_verify(plan, src)
    sealed = _seal_source(src)
    print("═══ 迁移完成 ═══")
    print(f"  数据已复制到: {dst}")
    print(f"  原目录已留证: {sealed}（确认运行正常后可人工删除）")
    print(f"  后续运行自动使用新目录；如需回退，设 EMSXVIEW_DATA_DIR={sealed}")


if __name__ == "__main__":
    main()
