# B1→B4 增量同步恢复执行计划

> 创建日期: 2026-06-15 | 关联: [控制中心](../data_management_refactoring_control.md) B4 行

## 零、问题诊断

### 根因

| 缺陷 | 说明 |
|------|------|
| **B2 双写开关未生效** | `PARTITION_DUAL_WRITE` 环境变量默认为 `"0"`，B1 迁移后管线继续只写 `processed_fills.db`，分区库未收到新数据 |
| **静默失败** | 双写代码中异常日志级别为 `debug`，即使环境变量设为 `"1"` 但连接失败也不会报警 |
| **3 个 ticker 写入方法无双写路径** | 当前无新数据写入这些方法，故行数差值集中在前 5 表 |

### 影响范围

```
B1 迁移时间点 (9表行数 = 分区库)
        │
        ├── B1→现在: processed_fills.db 新增数据 → 单写旧库
        │   execution_history 4表: +7,538 行 → 未同步
        │   order_label:          +7,156 行 → 未同步
        │   ticker 4表:           无新增 → 行数一致
        │
        └── 当前: processed_fills.db 行数 > 分区库行数

B4 清理脚本的 _verify_row_counts() 会被阻塞 (行数不匹配)
```

### 补救原则

- **不覆盖已有数据**：使用 `INSERT OR IGNORE`，仅插入分区库中不存在的行
- **不影响已验收步骤**：A7/A8/B1/B2/B3 状态不变
- **B4 安全网完整保留**：仍执行备份 → 校验 → DROP → VACUUM 全流程

---

## 一、执行步骤

### Phase 1: 诊断确认 (只读)

**目的**：量化差异，确认环境状态

```powershell
# 1.1 确认双写开关状态
$env:PARTITION_DUAL_WRITE
# 期望: 空或 "0" (未启用)

# 1.2 确认数据目录路径
python -c "from DataPipeline.config import Config; print(Config.DATA_DIR)"
```

**1.3 执行差异分析**（在 DataPipeline 环境中运行）：

```python
# 另存为 scripts/diagnose_b4_gap.py，执行:
import sqlite3
from DataPipeline.config import Config

TABLES = {
    Config.EXECUTION_HISTORY_DB: [
        "route_registry", "order_history", "route_history", "route_event_history"
    ],
    Config.TICKER_REGISTRY_DB: [
        "ticker_repository", "equ_ticker_registry", "ccy_ticker_registry",
        "ticker_date_mapping", "order_label"
    ],
}

src = sqlite3.connect(str(Config.PROCESSED_FILLS_DB))
for db_path, tables in TABLES.items():
    tgt = sqlite3.connect(str(db_path))
    for table in tables:
        src_count = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        tgt_count = tgt.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        status = "✓" if src_count == tgt_count else f"✗ diff={src_count - tgt_count}"
        print(f"[{status}] {table}: src={src_count} tgt={tgt_count}")
    tgt.close()
src.close()
```

**门禁**：确认差异表清单与预期一致（execution_history 4表 + order_label）

---

### Phase 2: 增量同步 (写入分区库)

**目的**：将 `processed_fills.db` 中有但分区库中缺失的行 INSERT 到对应分区库

**策略**：每张表使用 `INSERT OR IGNORE INTO target.table SELECT * FROM source.table WHERE pk NOT IN (SELECT pk FROM target.table)`

创建增量同步脚本 `scripts/sync_b4_incremental.py`：

```python
"""B4 增量同步: 将 B1 迁移后 processed_fills.db 新增数据同步到分区库。

使用 INSERT OR IGNORE 确保幂等，可安全重跑。
"""

import sqlite3
import sys
from DataPipeline.config import Config

# 表 → 目标库 + 主键列 (用于去重)
SYNC_TABLES: list[tuple[str, str, list[str]]] = [
    # (表名, 目标库属性名, 主键列)
    ("route_registry",       "EXECUTION_HISTORY_DB", ["OrderId", "RouteId"]),
    ("order_history",        "EXECUTION_HISTORY_DB", ["OrderId", "order_as_of_date"]),
    ("route_history",        "EXECUTION_HISTORY_DB", ["OrderId", "RouteId", "order_as_of_date"]),
    ("route_event_history",  "EXECUTION_HISTORY_DB", ["event_id"]),
    ("ticker_repository",    "TICKER_REGISTRY_DB",   ["equ_ticker"]),
    ("equ_ticker_registry",  "TICKER_REGISTRY_DB",   ["equ_ticker"]),
    ("ccy_ticker_registry",  "TICKER_REGISTRY_DB",   ["ccy_ticker"]),
    ("ticker_date_mapping",  "TICKER_REGISTRY_DB",   ["ticker", "ticker_type", "order_as_of_date"]),
    ("order_label",          "TICKER_REGISTRY_DB",   ["OrderId"]),
]


def sync_table(src_conn, tgt_conn, table: str, pk_cols: list[str]) -> int:
    """增量同步单表，返回写入行数。"""
    # 获取目标库已有主键
    pk_list = ", ".join(pk_cols)
    pk_where = " AND ".join(f"t.{c} = s.{c}" for c in pk_cols)

    # 查找源库有但目标库没有的行
    sql = f"""
        SELECT s.* FROM {table} s
        WHERE NOT EXISTS (
            SELECT 1 FROM {table} t WHERE {pk_where}
        )
    """
    # SQLite 跨库查询不支持，需分两步做
    # 替代方案: 读取目标库所有主键 → 在源库查找不在集合内的行

    tgt_pks = set()
    for row in tgt_conn.execute(f"SELECT {pk_list} FROM {table}"):
        tgt_pks.add(row)

    src_cols = [c[1] for c in src_conn.execute(f"PRAGMA table_info({table})")]
    placeholders = ", ".join("?" * len(src_cols))
    insert_sql = f"INSERT OR IGNORE INTO {table} ({', '.join(src_cols)}) VALUES ({placeholders})"

    inserted = 0
    for row in src_conn.execute(f"SELECT * FROM {table}"):
        pk_vals = tuple(row[src_cols.index(c)] for c in pk_cols)
        if pk_vals not in tgt_pks:
            tgt_conn.execute(insert_sql, row)
            inserted += 1

    tgt_conn.commit()
    return inserted


def main():
    src = sqlite3.connect(str(Config.PROCESSED_FILLS_DB))
    total_inserted = 0

    for table, db_attr, pk_cols in SYNC_TABLES:
        tgt_path = getattr(Config, db_attr)
        tgt = sqlite3.connect(str(tgt_path))

        src_count = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        tgt_before = tgt.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        diff = src_count - tgt_before
        if diff <= 0:
            print(f"[✓] {table}: 已同步 (src={src_count}, tgt={tgt_before})")
            tgt.close()
            continue

        print(f"[→] {table}: 差异 {diff} 行, 开始同步...")
        inserted = sync_table(src, tgt, table, pk_cols)
        total_inserted += inserted

        tgt_after = tgt.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        match = "✓" if tgt_after == src_count else "✗"
        print(f"  [{match}] {table}: {tgt_before} → {tgt_after} (新增 {inserted})")

        tgt.close()

    src.close()
    print(f"\n总计新增: {total_inserted} 行")
    return 0 if total_inserted >= 0 else 1


if __name__ == "__main__":
    sys.exit(main())
```

**执行**：

```powershell
python scripts/sync_b4_incremental.py
```

---

### Phase 3: 全量验证 (只读)

**目的**：确认 9 张表行数全部一致

**3.1 使用 B1 迁移脚本的验证模式**：

```powershell
python scripts/migrate_partition.py --verify
```

**3.2 使用 B4 清理脚本的 DRY-RUN (含行数校验)**：

```powershell
python scripts/cleanup_partitioned_db.py --dry-run
```

输出应显示 9 张表全部 `✓`。

**门禁**：9 表行数 100% 匹配

---

### Phase 4: 执行 B4 清理

**前置条件**：Phase 3 全部通过

```powershell
# 4.1 DRY-RUN 确认
python scripts/cleanup_partitioned_db.py --dry-run

# 4.2 执行清理 (备份 → 校验 → DROP → VACUUM → 创建观察期清单)
python scripts/cleanup_partitioned_db.py --confirm-cleanup
```

**B4 执行流程**（脚本自动完成）：

| 步骤 | 操作 | 安全网 |
|------|------|--------|
| Preflight | 磁盘空间 > 1.2x、分区库存在、quick_check | 任一失败中止 |
| Backup | `processed_fills.db` → `.bak_migration_20260615` | SHA256 哈希 |
| Verify | 9 表源库 vs 分区库行数对比 | 不匹配中止 |
| DROP | DROP TABLE IF EXISTS (9张表) | .BAK 可恢复 |
| VACUUM | 释放 ~10 GB 空间 | .BAK 可恢复 |
| Manifest | 创建 `observation_B4.json` | 14天观察期 |

**4.3 观察期启动**：

观察期由 `daily_observation_check.py --phase B4` 自动执行（已在 Windows Task Scheduler 注册），包含 6 项检查：

- BAK 文件完整性校验 (SHA256)
- 分区库 PRAGMA integrity_check
- TCA 查询 API 延迟对比基线
- 管线运行状态 (最新周期成功)
- 分区库体积跳变检测 (±20%)
- 跨库关联完整性 (order_history JOIN route_history 抽样)

**门禁**：连续 14 天 `all_pass: true` 且无 `blocking_conditions_triggered`

---

## 二、风险与回退

| 风险 | 概率 | 缓解措施 |
|------|------|----------|
| 增量同步插入重复数据 | 低 | `INSERT OR IGNORE` + 主键去重，幂等可重跑 |
| 同步期间管线写入冲突 | 低 | SQLite WAL 模式允许并发读；建议同步期间暂停管线 |
| 磁盘空间不足 | 低 | Phase 1 预检磁盘空间 > 1.2x |
| B4 清理后发现问题 | 低 | .BAK 物理备份保留 14 天，可直接恢复 |

**回退方案**：若 B4 观察期出现 blocking condition：

```powershell
# 恢复 processed_fills.db
copy data\processed_fills.bak_migration_20260615 data\processed_fills.db

# 通知 daily_observation_check 停止 B4 检查
# observation_B4.json 中 blocking_conditions_triggered 已自动记录
```

---

## 三、影响评估

| 已验收步骤 | 是否受影响 | 原因 |
|-----------|-----------|------|
| A7 (raw_bdib 收缩) | 否 | 独立数据库，无关联 |
| A8 (processed_raw_bdib 退役) | 否 | 独立数据库，无关联 |
| B1 (分区迁移) | 否 | 增量同步仅补数据，不覆盖已有行 |
| B2 (双写) | 否 | 设计缺陷已识别，不改变 B2 代码 |
| B3 (读路径切换) | 否 | `PARTITION_READ_NEW` 开关不受影响 |

---

## 四、执行检查清单

- [ ] Phase 1: `PARTITION_DUAL_WRITE` 状态确认
- [ ] Phase 1: 差异表清单与预期一致
- [ ] Phase 2: 增量同步脚本执行成功
- [ ] Phase 3: `migrate_partition.py --verify` 全部通过
- [ ] Phase 3: `cleanup_partitioned_db.py --dry-run` 行数校验通过
- [ ] Phase 4: `cleanup_partitioned_db.py --confirm-cleanup` 执行成功
- [ ] Phase 4: `observation_B4.json` 已创建
- [ ] Phase 4: 管线连续运行 2 周期无异常
- [ ] 更新 `data_management_refactoring_control.md` B4 状态为 ✅
