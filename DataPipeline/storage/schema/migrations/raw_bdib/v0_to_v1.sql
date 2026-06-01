-- Migration: raw_bdib v0 -> v1
-- Baseline schema version registration.
-- Table creation is handled by inline DDL (idempotent CREATE TABLE IF NOT EXISTS).
-- This migration marks the current schema as v1 for future forward migrations.

BEGIN;
PRAGMA user_version = 1;
COMMIT;
