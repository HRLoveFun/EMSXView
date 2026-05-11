// DatabaseView — read model for /api/db/* endpoints.
// Mirrors platform_data/repositories.py dataclasses.

export type DatabaseHealth = 'ok' | 'stale' | 'empty' | 'missing' | 'error';

export interface DatabaseOverview {
  key: string;
  label: string;
  path: string;
  description: string;
  exists: boolean;
  size_bytes: number;
  last_modified: string | null;
  wal_active: boolean;
  table_count: number;
  total_rows: number;
  latest_trade_date: string | null;
  earliest_trade_date: string | null;
  distinct_trade_dates: number;
  health: DatabaseHealth;
  error?: string | null;
}

export interface DateRowCount {
  trade_date: string;
  row_count: number;
}

export interface TableSummary {
  name: string;
  description: string;
  primary_key: string | null;
  date_column: string | null;
  row_count: number;
  latest_trade_date: string | null;
  earliest_trade_date: string | null;
  distinct_trade_dates: number;
  per_date_counts: DateRowCount[];
}

export interface DatabaseSummary {
  key: string;
  label: string;
  path: string;
  exists: boolean;
  size_bytes: number;
  last_modified: string | null;
  description: string;
  tables: TableSummary[];
  error?: string | null;
}

export interface IntegrityIssue {
  code: string;
  severity: 'info' | 'warning' | 'error' | string;
  message: string;
  count?: number;
}

export interface IntegrityReport {
  key: string;
  checked_at: string;
  issues: IntegrityIssue[];
}

export interface OverviewResponse {
  success: boolean;
  items: DatabaseOverview[];
}

export interface SummaryResponse extends DatabaseSummary {
  success: boolean;
}

export interface IntegrityResponse extends IntegrityReport {
  success: boolean;
}

// ── Schema & sample (per-table inspection) ──────────────────────────────────

export interface ColumnInfo {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: number;       // 0 = not in PK, otherwise 1-based PK position
  default_value: string | null;
}

export interface IndexInfo {
  name: string;
  unique: boolean;
  columns: string[];
}

export interface SchemaResponse {
  success: boolean;
  database_key: string;
  table: string;
  description: string;
  primary_key_display: string | null;
  columns: ColumnInfo[];
  indexes: IndexInfo[];
}

export interface ColumnAnomaly {
  column: string;
  severity: 'info' | 'warning' | 'error' | string;
  code: string;
  message: string;
}

export type SampleCell = string | number | boolean | null;

export interface SampleResponse {
  success: boolean;
  database_key: string;
  table: string;
  columns: string[];
  rows: SampleCell[][];
  row_count_estimate: number;
  fetched_at: string;
  order_by: string | null;
  anomalies: ColumnAnomaly[];
}

// Pipeline job types — identical shape to costview TriggerUpdate/UpdateStatus.
export interface TriggerUpdateResponse {
  job_id: string;
  status: string;
  message: string;
}

export interface StageInfo {
  name: string;
  label: string;
  progress: number;
  detail: string | null;
}

export interface UpdateStatusResponse {
  job_id: string;
  status: 'started' | 'running' | 'completed' | 'failed';
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  stage: StageInfo | null;
  overall_progress: number;
  last_activity_at: string | null;
}
