"""057 DL-06 — 盘中库契约测试（镜像与父计划 §4.0 冻结条款互锁）。

锁死行为：
1. INTRADAY_TABLES 与 §4.0 冻结条款逐字一致（6 张）；
2. TABLE_COLUMNS 覆盖全部表、列名非空无重复；
3. intraday_db_path 行为（目录/模板/日期原样）；
4. manifest 条目字段与「as_of/水位/行数/状态/last_error」一致；
5. provisional/读侧路由/守恒审计/保留期常量；
6. order_intent 列与 DL-01 OrderIntent 契约字段一一对应（跨契约防漂移）。
"""

from __future__ import annotations

import sys
from dataclasses import fields
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

REPO_ROOT = API_ROOT.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_access.config import Config, intraday_db_path  # noqa: E402
from platform_data.contracts import (  # noqa: E402
    CONSERVATION_AUDIT_RULE,
    INTRADAY_DB_FILE_TEMPLATE,
    INTRADAY_DIR_NAME,
    INTRADAY_MANIFEST_FILE_NAME,
    INTRADAY_RETENTION_DAYS,
    INTRADAY_STORE_VERSION,
    INTRADAY_TABLES,
    READ_ROUTE_RULE,
    TABLE_COLUMNS,
    DataFreshness,
    IntradayDatasetStatus,
    IntradayManifest,
)
from platform_data.contracts import OrderIntent  # noqa: E402

# 父计划 §4.0 冻结条款（057 plan.md：盘中库表 intraday_fills、blotter_snapshots、
# order_intent、route_params_snapshot、bars_10s_t0、snapshot_t0）
FROZEN_TABLES = {
    "intraday_fills",
    "blotter_snapshots",
    "order_intent",
    "route_params_snapshot",
    "bars_10s_t0",
    "snapshot_t0",
}


class TestFrozenTables:
    """用例 1/2：表名与列结构。"""

    def test_tables_match_frozen_clause(self):
        assert set(INTRADAY_TABLES) == FROZEN_TABLES
        assert len(INTRADAY_TABLES) == 6

    def test_table_columns_cover_all_tables(self):
        assert set(TABLE_COLUMNS) == FROZEN_TABLES
        for table, columns in TABLE_COLUMNS.items():
            assert columns, f"{table} 列名为空"
            assert len(set(columns)) == len(columns), f"{table} 列名重复"
            assert all(isinstance(c, str) and c for c in columns), table

    def test_key_columns_present(self):
        # 关键标识列（跨表 join 与读侧路由依赖）
        assert "order_as_of_date" in TABLE_COLUMNS["intraday_fills"]
        assert "order_key" in TABLE_COLUMNS["order_intent"]
        assert "equ_ticker" in TABLE_COLUMNS["bars_10s_t0"]
        assert "equ_ticker" in TABLE_COLUMNS["snapshot_t0"]
        assert "export_ts" in TABLE_COLUMNS["blotter_snapshots"]


class TestDbPath:
    """用例 3：盘中库文件路径规则。"""

    def test_path_rule(self):
        path = intraday_db_path("20261022")
        assert path.parent == Config.INTRADAY_DIR
        assert path.name == "intraday_20261022.db"
        assert Config.INTRADAY_DIR.name == INTRADAY_DIR_NAME
        assert Config.INTRADAY_DIR.parent == Config.DATA_DIR

    def test_template_constant(self):
        assert INTRADAY_DB_FILE_TEMPLATE == "intraday_YYYYMMDD.db"
        assert INTRADAY_MANIFEST_FILE_NAME == "intraday_manifest.json"
        assert Config.INTRADAY_MANIFEST_FILE.name == INTRADAY_MANIFEST_FILE_NAME


class TestManifest:
    """用例 4：manifest 条目字段（as_of/水位/行数/状态/last_error）。"""

    def test_dataset_status_fields(self):
        names = {f.name for f in fields(IntradayDatasetStatus)}
        assert names == {"dataset", "as_of", "watermark", "row_count", "status", "last_error"}

    def test_manifest_fields(self):
        names = {f.name for f in fields(IntradayManifest)}
        assert {"manifest_version", "generated_at", "trade_date", "datasets"} <= names

    def test_data_freshness_fields(self):
        names = {f.name for f in fields(DataFreshness)}
        assert names == {"dataset", "as_of", "lag_minutes"}


class TestSemantics:
    """用例 5：provisional/读侧路由/守恒审计/保留期常量。"""

    def test_route_and_audit_rules(self):
        assert READ_ROUTE_RULE == "formal-first"
        assert CONSERVATION_AUDIT_RULE == "diff-to-audit"

    def test_retention(self):
        assert INTRADAY_RETENTION_DAYS == 30

    def test_version(self):
        assert INTRADAY_STORE_VERSION == "intraday-store-v1"


class TestCrossContractAlignment:
    """用例 6：order_intent 列与 DL-01 OrderIntent 字段一一对应（跨契约防漂移）。"""

    def test_order_intent_columns_match_dl01_contract(self):
        contract_fields = {f.name for f in fields(OrderIntent)}
        table_columns = set(TABLE_COLUMNS["order_intent"])
        # 入库列 = 契约字段 + mapping_version（DL-01 预留的版本列）
        assert contract_fields <= table_columns
        assert "mapping_version" in table_columns
        # 无契约外列（除 mapping_version）
        assert table_columns - contract_fields == {"mapping_version"}
