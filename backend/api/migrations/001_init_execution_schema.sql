-- Sprint 1: initial durable execution schema

CREATE TABLE IF NOT EXISTS orders_projection (
  id BIGSERIAL PRIMARY KEY,
  sequence INTEGER NOT NULL UNIQUE,
  order_id VARCHAR(64) NOT NULL,
  status VARCHAR(32) NOT NULL,
  trader VARCHAR(64) NOT NULL,
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_projection_order_id ON orders_projection (order_id);
CREATE INDEX IF NOT EXISTS idx_orders_projection_status ON orders_projection (status);
CREATE INDEX IF NOT EXISTS idx_orders_projection_trader ON orders_projection (trader);

CREATE TABLE IF NOT EXISTS routes_projection (
  id BIGSERIAL PRIMARY KEY,
  sequence INTEGER NOT NULL,
  route_id INTEGER NOT NULL,
  status VARCHAR(32) NOT NULL,
  broker VARCHAR(64) NOT NULL,
  payload JSONB NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_routes_projection_sequence_route_id UNIQUE (sequence, route_id)
);

CREATE INDEX IF NOT EXISTS idx_routes_projection_sequence ON routes_projection (sequence);
CREATE INDEX IF NOT EXISTS idx_routes_projection_route_id ON routes_projection (route_id);
CREATE INDEX IF NOT EXISTS idx_routes_projection_status ON routes_projection (status);
CREATE INDEX IF NOT EXISTS idx_routes_projection_broker ON routes_projection (broker);

CREATE TABLE IF NOT EXISTS audit_events (
  id BIGSERIAL PRIMARY KEY,
  action VARCHAR(64) NOT NULL,
  actor VARCHAR(64) NOT NULL,
  endpoint VARCHAR(128) NOT NULL,
  result VARCHAR(32) NOT NULL,
  correlation_id VARCHAR(128),
  payload_summary TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_events_action ON audit_events (action);
CREATE INDEX IF NOT EXISTS idx_audit_events_actor ON audit_events (actor);
CREATE INDEX IF NOT EXISTS idx_audit_events_correlation_id ON audit_events (correlation_id);

CREATE TABLE IF NOT EXISTS subscription_watermarks (
  stream_name VARCHAR(64) PRIMARY KEY,
  last_sequence INTEGER NOT NULL DEFAULT 0,
  last_event_time TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
