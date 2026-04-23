-- Sprint 5: parent-child execution model

CREATE TABLE IF NOT EXISTS parent_executions (
  id BIGSERIAL PRIMARY KEY,
  sequence INTEGER NOT NULL,
  order_id VARCHAR(64) NOT NULL,
  trader VARCHAR(64) NOT NULL,

  -- Objective
  schedule_type VARCHAR(16) NOT NULL,
  target_quantity INTEGER NOT NULL,
  filled_quantity INTEGER NOT NULL DEFAULT 0,

  -- Scheduling window
  start_time TIMESTAMPTZ,
  end_time TIMESTAMPTZ,

  -- Participation / urgency
  participation_rate DOUBLE PRECISION,
  urgency VARCHAR(16),

  -- Benchmark reference
  benchmark_price DOUBLE PRECISION,

  -- Broker / strategy defaults for child slices
  broker VARCHAR(64),
  strategy_params JSONB,

  status VARCHAR(16) NOT NULL DEFAULT 'PENDING',

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parent_executions_sequence ON parent_executions (sequence);
CREATE INDEX IF NOT EXISTS idx_parent_executions_order_id ON parent_executions (order_id);
CREATE INDEX IF NOT EXISTS idx_parent_executions_trader ON parent_executions (trader);
CREATE INDEX IF NOT EXISTS idx_parent_executions_status ON parent_executions (status);

CREATE TABLE IF NOT EXISTS child_slices (
  id BIGSERIAL PRIMARY KEY,
  parent_id BIGINT NOT NULL REFERENCES parent_executions (id),
  sequence INTEGER NOT NULL,
  route_id INTEGER,

  slice_index INTEGER NOT NULL,
  planned_quantity INTEGER NOT NULL,
  filled_quantity INTEGER NOT NULL DEFAULT 0,

  scheduled_start TIMESTAMPTZ,
  scheduled_end TIMESTAMPTZ,

  limit_price DOUBLE PRECISION,
  strategy_params JSONB,

  status VARCHAR(16) NOT NULL DEFAULT 'PENDING',

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_child_slices_parent_id ON child_slices (parent_id);
CREATE INDEX IF NOT EXISTS idx_child_slices_sequence ON child_slices (sequence);
CREATE INDEX IF NOT EXISTS idx_child_slices_route_id ON child_slices (route_id);
CREATE INDEX IF NOT EXISTS idx_child_slices_status ON child_slices (status);
