---
name: schema-designer
description: "Design SQLite/relational schemas with built-in observability, traceability, and reproducibility. Use when adding new tables, refactoring existing schemas, planning storage for analytical pipelines, or sharing schema patterns across modules."
---
# Schema Designer

Reusable design discipline for the EMSX project's analytical/pipeline databases (CostView regime, attribution, research outputs, future modules). Built from the regime layer schema review (2026-04).

## When to Use

- Adding new tables to an existing DB (`processed_fills.db`, `regime.db`, etc.)
- Creating a new SQLite database for a new analytical layer
- Refactoring an existing schema that lacks audit/traceability
- Reviewing a peer's schema PR

## Non-negotiable Principles

Each principle maps to a concrete schema element. **A schema review is a 9-row checklist.**

| # | Engineering need | Schema element |
|---|---|---|
| 1 | Task logic clear | Header comment block on every table: `-- PURPOSE / -- WRITTEN BY / -- READ BY / -- GRAIN`. `GRAIN` must describe row semantics in one sentence. |
| 2 | Steps build up incrementally | Tables use 4 fixed prefixes: `ref_*` (manual/small) â†’ `daily_*` (per-day batch) â†’ `fill_*` / `event_*` (per-event derived) â†’ `audit_*` (run journals, config versions). Upper layers only read lower layers. |
| 3 | Changes traceable | All non-`ref_*` tables MUST have `ingested_at TIMESTAMP NOT NULL` and `source_version TEXT NOT NULL`. `ref_*` tables are tracked via git on the source file. |
| 4 | Results verifiable | Every DB ships a `<module>_status` SQL VIEW summarizing row count, min/max date, last ingestion timestamp per table. A `validate_<module>.py` CLI prints this view + integrity diffs. |
| 5 | Errors discoverable | Use `NOT NULL`, `CHECK` (numeric ranges, enums), `UNIQUE`/`PRIMARY KEY`. Writes use `INSERT ... ON CONFLICT DO UPDATE` (idempotent). DB schema version pinned via `PRAGMA user_version` AND a code constant â€” both must match at startup. |
| 6 | Process controllable | All writes inside `BEGIN IMMEDIATE` transactions. Batch size â‰¤ 5000 rows. On failure â†’ rollback, no half-state. Parameterized analytical tables (`fill_*_labels`) are append-only with `config_version` in PK; old rows preserved. |
| 7 | Experience captured | DDL lives in a single module-level `schema.py` (DDL strings + `create_all()` helper). New columns require bumping `user_version` AND adding a `migrations/vN_to_vN+1.sql` file. |
| 8 | Don't forget what came before | Every DB has `audit_pipeline_runs` (run_id, stage_name, target_date_range, rows_written, status, started_at, finished_at, error_message). Recovery jobs query this first. |
| 9 | User-friendly | Manual-edit files (json/csv) get a `validate_<file>.py` that prints row + column + expected value on error. CLI/frontend reads `<module>_status` view, not raw tables. |

## Standard Table Header Template

```sql
-- ============================================================================
-- <table_name>
-- PURPOSE   : <one sentence: what business question this answers>
-- WRITTEN BY: <stage / script path>
-- READ BY   : <downstream consumers>
-- GRAIN     : One row per (<key columns>)
-- MNEMONICS : <Bloomberg fields used, if any>
-- DERIVED   : <computed columns and their formula, if any>
-- ============================================================================
CREATE TABLE IF NOT EXISTS <table_name> (
    ...
    source_version  TEXT NOT NULL,
    ingested_at     TIMESTAMP NOT NULL,
    PRIMARY KEY (...)
);
```

## Standard Audit Tables (every analytical DB)

```sql
-- One row per parameter set. Append-only. is_active filters to current.
CREATE TABLE audit_<module>_config_versions (
    version_id   TEXT PRIMARY KEY,           -- e.g. 'v2026.04.27'
    created_at   TIMESTAMP NOT NULL,
    is_active    INTEGER NOT NULL DEFAULT 0 CHECK (is_active IN (0,1)),
    -- module-specific params as columns or JSON
    description  TEXT
);
CREATE UNIQUE INDEX uniq_active_<module>_config
    ON audit_<module>_config_versions(is_active) WHERE is_active = 1;

-- One row per stage execution.
CREATE TABLE audit_pipeline_runs (
    run_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_name        TEXT NOT NULL,
    config_version    TEXT,
    target_start_date TEXT,
    target_end_date   TEXT,
    rows_written      INTEGER,
    rows_updated      INTEGER,
    status            TEXT NOT NULL CHECK (status IN ('running','success','failed','rollback')),
    error_message     TEXT,
    run_started_at    TIMESTAMP NOT NULL,
    run_finished_at   TIMESTAMP,
    duration_sec      REAL,
    host              TEXT,
    schema_version    TEXT NOT NULL
);
CREATE INDEX idx_runs_stage_started ON audit_pipeline_runs(stage_name, run_started_at DESC);
```

## Project Conventions

- **Date type**: `TEXT 'YYYY-MM-DD'`. Project standard, unified across all DBs (regime layer locked this in M1; legacy `bdib_daily_summary.YYYYMMDD` is acceptable but new tables MUST use `YYYY-MM-DD`).
- **Pragmas**: every DB opens with `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA user_version=N;`
- **Naming**: `snake_case`, plural-rare (use `daily_vol_regime` not `daily_vol_regimes`).
- **Index discipline**: PRIMARY KEY suffices for lookups by full key. Add explicit indexes ONLY for known query patterns (date range, market filter).
- **No surrogate IDs unless needed**: composite natural keys preferred (e.g., `(equ_ticker, trade_date)`).
- **Append-only research tables** include `config_version` in PK so reproducibility is preserved across param drift.

## Migration Discipline

Directory layout (every analytical DB):
```
CostView/src/<module>/
â”œâ”€â”€ schema.py                 # DDL strings + create_all() + SCHEMA_VERSION constant
â”œâ”€â”€ migrations/
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ v1_to_v2.sql
â”‚   â””â”€â”€ apply.py              # reads PRAGMA user_version, applies pending migrations
```

Workflow on any DDL change:
1. Bump `SCHEMA_VERSION` in `schema.py`
2. Add `migrations/vN_to_vN+1.sql` (forward-only)
3. Document the change in the migration file header (one-line WHY)
4. Run tests; `apply.py` must run cleanly on a copy of production DB

## Review Checklist (use before merging any new DDL)

- [ ] Table header block present and `GRAIN` is one sentence
- [ ] Layer prefix matches dependency direction
- [ ] `ingested_at` + `source_version` present (non-ref tables)
- [ ] `<module>_status` view updated to include the new table
- [ ] CHECK / NOT NULL / FK constraints reflect business rules
- [ ] Writes are idempotent (`ON CONFLICT DO UPDATE` or natural-key UPSERT)
- [ ] Dates use `'YYYY-MM-DD'` TEXT
- [ ] If a research/analytics output table: PK includes `config_version`, append-only enforced
- [ ] `audit_pipeline_runs` is written by the producing stage
- [ ] `SCHEMA_VERSION` bumped, migration file added
- [ ] `validate_<module>.py` runs without error on sample data

## Anti-patterns to reject

- Tables without `ingested_at` (untraceable writes)
- Mutating analytical results in place (loses reproducibility)
- DDL scattered across multiple files in one module
- Missing `audit_pipeline_runs` write (recovery becomes guesswork)
- Hand-rolled INSERT-or-UPDATE logic instead of `ON CONFLICT DO UPDATE`
- Composite PK ordering chosen by tuple alphabet rather than query patterns

