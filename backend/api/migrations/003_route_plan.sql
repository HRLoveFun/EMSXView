-- 003: Route Plan & Sub-Order Proposal tables

CREATE TABLE IF NOT EXISTS route_plans (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(128) NOT NULL,
  description TEXT,

  -- Match criteria
  match_market VARCHAR(32) NOT NULL DEFAULT '',
  match_symbol VARCHAR(64),
  match_side VARCHAR(8) NOT NULL DEFAULT 'BOTH',
  match_portfolio VARCHAR(64),
  match_trader VARCHAR(64),
  match_exchange VARCHAR(32),
  match_currency VARCHAR(8),

  -- Activation / submission mode
  activation_mode VARCHAR(16) NOT NULL DEFAULT 'MANUAL',
  submission_mode VARCHAR(16) NOT NULL DEFAULT 'MANUAL_CONFIRM',

  -- Status
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  priority INTEGER NOT NULL DEFAULT 0,

  -- Split strategy
  split_type VARCHAR(16) NOT NULL DEFAULT 'BROKER_SPLIT',

  -- Time schedule config (for TIME_SCHEDULE or HYBRID)
  schedule_type VARCHAR(16),
  num_slices INTEGER,
  default_start_offset_min INTEGER,
  default_end_time_local VARCHAR(8),
  participation_rate DOUBLE PRECISION,

  -- Default route params
  default_broker VARCHAR(64),
  default_order_type VARCHAR(16),
  default_tif VARCHAR(8),
  default_strategy_params JSONB,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_plans_enabled ON route_plans (enabled);
CREATE INDEX IF NOT EXISTS idx_route_plans_activation ON route_plans (activation_mode);
CREATE INDEX IF NOT EXISTS idx_route_plans_match_market ON route_plans (match_market);
CREATE INDEX IF NOT EXISTS idx_route_plans_match_symbol ON route_plans (match_symbol);


CREATE TABLE IF NOT EXISTS route_plan_allocations (
  id BIGSERIAL PRIMARY KEY,
  route_plan_id BIGINT NOT NULL REFERENCES route_plans (id) ON DELETE CASCADE,

  broker VARCHAR(64) NOT NULL,
  allocation_type VARCHAR(16) NOT NULL DEFAULT 'PERCENTAGE',
  allocation_value DOUBLE PRECISION NOT NULL,

  -- Per-broker route parameters
  order_type VARCHAR(16),
  limit_price_offset DOUBLE PRECISION,
  strategy_params JSONB,

  sort_order INTEGER NOT NULL DEFAULT 0,

  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_route_plan_allocations_plan ON route_plan_allocations (route_plan_id);


CREATE TABLE IF NOT EXISTS sub_order_proposals (
  id BIGSERIAL PRIMARY KEY,
  route_plan_id BIGINT REFERENCES route_plans (id) ON DELETE SET NULL,
  parent_order_id VARCHAR(64) NOT NULL,

  -- Route identity (populated after EMSX submission)
  route_id INTEGER,

  -- Proposal details
  broker VARCHAR(64) NOT NULL,
  quantity INTEGER NOT NULL,
  order_type VARCHAR(16),
  limit_price DOUBLE PRECISION,
  tif VARCHAR(8),
  strategy_params JSONB,

  -- Time schedule info
  slice_index INTEGER,
  scheduled_start TIMESTAMPTZ,
  scheduled_end TIMESTAMPTZ,

  -- Parent order snapshot
  parent_symbol VARCHAR(32),
  parent_side VARCHAR(8),
  parent_trader VARCHAR(64),
  parent_portfolio VARCHAR(64),

  -- Status
  status VARCHAR(16) NOT NULL DEFAULT 'PENDING_CONFIRM',

  confirmed_at TIMESTAMPTZ,
  submitted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sub_order_proposals_status ON sub_order_proposals (status);
CREATE INDEX IF NOT EXISTS idx_sub_order_proposals_parent ON sub_order_proposals (parent_order_id);
CREATE INDEX IF NOT EXISTS idx_sub_order_proposals_route_plan ON sub_order_proposals (route_plan_id);
