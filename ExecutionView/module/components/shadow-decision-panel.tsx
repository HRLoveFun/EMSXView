import { useEffect, useState } from 'react';
import { Loader2, Scale } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { apiFetch } from '@execution/services/execution-api';

// ============================================================================
// Shadow decision side-by-side (057 DL-22/215) — read-only
// ============================================================================

export interface ShadowCandidate {
  broker: string;
  quantity: number;
  participation_pct?: number | null;
  strategy_params?: Record<string, unknown>;
  rationale?: string;
  quote_spread_bps?: number | null;
  estimated_cost_bps?: number | null;
}

export interface ShadowActualRoute {
  route_id: string;
  broker: string;
  quantity: number;
  strategy_type?: string;
  status?: string;
  filled_quantity?: number;
}

export interface ShadowViolation {
  code: string;
  message?: string;
  severity?: string;
}

export interface ShadowDecisionPayload {
  candidates?: ShadowCandidate[];
  actual_routes?: ShadowActualRoute[];
  rewrite_reason?: string;
  intent?: string;
  intent_source?: string;
  source?: string;
  quote_spread_bps?: number | null;
  constraint_violations?: ShadowViolation[];
  schema_version?: string;
}

export interface ShadowDecisionRecord {
  decision_id: string;
  order_id: string;
  as_of: string;
  source?: string;
  schema_version: string;
  payload: ShadowDecisionPayload;
}

interface ShadowDecisionPanelProps {
  orderId?: string | null;
}

function _fmt(value: number | null | undefined, digits = 2): string {
  return value == null ? '—' : value.toFixed(digits);
}

export function ShadowDecisionPanel({ orderId }: ShadowDecisionPanelProps) {
  const [record, setRecord] = useState<ShadowDecisionRecord | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    // 在微任务中触发加载（同 SubOrderReviewPanel），避免 effect 同步路径 setState
    queueMicrotask(() => {
      if (cancelled) return;
      if (!orderId) {
        setRecord(null);
        setError('');
        setIsLoading(false);
        return;
      }
      setIsLoading(true);
      setError('');
      apiFetch<{ records: ShadowDecisionRecord[] }>(
        `/api/routing-decisions?order_id=${encodeURIComponent(orderId)}&limit=1`,
      )
        .then(result => {
          if (cancelled) return;
          if (result.success && result.data) {
            setRecord(result.data.records?.[0] ?? null);
          } else {
            setRecord(null);
            setError(result.error || 'Failed to load shadow decision');
          }
        })
        .catch(() => {
          if (!cancelled) {
            setRecord(null);
            setError('Failed to load shadow decision');
          }
        })
        .finally(() => {
          if (!cancelled) setIsLoading(false);
        });
    });
    return () => { cancelled = true; };
  }, [orderId]);

  if (!orderId) {
    return (
      <div className="text-xs text-muted-foreground">
        Select exactly one order to compare the engine suggestion with the actual routes.
      </div>
    );
  }
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading shadow decision…
      </div>
    );
  }
  if (error) {
    return <div className="text-xs text-destructive">{error}</div>;
  }
  if (!record) {
    return <div className="text-xs text-muted-foreground">No shadow decision for this order.</div>;
  }

  const payload = record.payload || {};
  const candidates = payload.candidates || [];
  const actual = payload.actual_routes || [];
  const violations = payload.constraint_violations || [];
  const source = payload.source || record.source || '—';
  const schema = payload.schema_version || record.schema_version;

  return (
    <div className="flex flex-col gap-2 text-xs">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="inline-flex items-center gap-1 font-semibold text-foreground">
          <Scale className="h-3.5 w-3.5" /> Shadow decision
        </span>
        <Badge variant="secondary">source: {source}</Badge>
        <Badge variant="outline">{schema}</Badge>
        <span className="text-muted-foreground">as of {record.as_of}</span>
        {payload.rewrite_reason && (
          <Badge variant={payload.rewrite_reason === 'UNCLASSIFIED' ? 'secondary' : 'destructive'}>
            {payload.rewrite_reason}
          </Badge>
        )}
        <span className="text-muted-foreground">spread {_fmt(payload.quote_spread_bps)} bps</span>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="rounded-md border p-2">
          <div className="font-semibold text-foreground mb-1">Suggested</div>
          {candidates.length === 0 ? (
            <div className="text-muted-foreground">No suggestion (no matching plan).</div>
          ) : (
            <table className="w-full text-left">
              <thead className="text-muted-foreground">
                <tr><th>Broker</th><th>Qty</th><th>Part.</th><th>Params</th></tr>
              </thead>
              <tbody>
                {candidates.map((candidate, index) => (
                  <tr key={`${candidate.broker}-${index}`}>
                    <td className="font-mono">{candidate.broker}</td>
                    <td>{candidate.quantity}</td>
                    <td>{candidate.participation_pct == null ? '—' : `${(candidate.participation_pct * 100).toFixed(1)}%`}</td>
                    <td className="font-mono text-[10px] truncate max-w-[140px]" title={JSON.stringify(candidate.strategy_params ?? {})}>
                      {JSON.stringify(candidate.strategy_params ?? {})}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="rounded-md border p-2">
          <div className="font-semibold text-foreground mb-1">Actual</div>
          {actual.length === 0 ? (
            <div className="text-muted-foreground">No actual route linked yet.</div>
          ) : (
            <table className="w-full text-left">
              <thead className="text-muted-foreground">
                <tr><th>Broker</th><th>Qty</th><th>Status</th><th>Route</th></tr>
              </thead>
              <tbody>
                {actual.map((route, index) => (
                  <tr key={`${route.route_id}-${index}`}>
                    <td className="font-mono">{route.broker}</td>
                    <td>{route.quantity}</td>
                    <td>{route.status || '—'}</td>
                    <td className="font-mono">{route.route_id || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div>
        <span className="font-semibold text-foreground">Constraints: </span>
        {violations.length === 0 ? (
          <span className="text-muted-foreground">none</span>
        ) : (
          <span className="inline-flex flex-wrap gap-1">
            {violations.map((violation, index) => (
              <Badge
                key={`${violation.code}-${index}`}
                variant={violation.severity === 'BLOCK' ? 'destructive' : 'secondary'}
                title={violation.message}
              >
                {violation.severity || 'WARN'} {violation.code}
              </Badge>
            ))}
          </span>
        )}
      </div>
    </div>
  );
}
