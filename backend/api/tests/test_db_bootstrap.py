from pathlib import Path
import sys

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from db import create_engine, get_database_url
from models.execution_state import Base

import config


def test_get_database_url_from_env(monkeypatch):
    url = "postgresql+asyncpg://user:pass@localhost:5432/testdb"
    monkeypatch.setenv("DATABASE_URL", url)
    assert get_database_url() == url


def test_default_database_url(monkeypatch, tmp_path):
    """DL-02/060：未显式设 DATABASE_URL 时默认运营库为 SQLite（D-4）。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(config.settings, "EMSXVIEW_OPS_DB_DIR", str(tmp_path))

    url = get_database_url()

    assert url.startswith("sqlite+aiosqlite:///")
    assert url.endswith("emsx_ops.db")
    assert str(tmp_path).replace("\\", "/") in url


def test_create_engine_uses_async_postgres_dialect():
    engine = create_engine("postgresql+asyncpg://emsx:emsx@postgres:5432/emsx")
    assert engine.url.get_backend_name() == "postgresql"


def test_execution_state_metadata_contains_core_tables():
    table_names = set(Base.metadata.tables.keys())
    assert {
        "orders_projection",
        "routes_projection",
        "audit_events",
        "subscription_watermarks",
    }.issubset(table_names)


def test_migration_sql_contains_core_tables():
    migration_file = Path(__file__).resolve().parents[1] / "migrations" / "001_init_execution_schema.sql"
    sql = migration_file.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS orders_projection" in sql
    assert "CREATE TABLE IF NOT EXISTS routes_projection" in sql
    assert "CREATE TABLE IF NOT EXISTS audit_events" in sql
    assert "CREATE TABLE IF NOT EXISTS subscription_watermarks" in sql
