/**
 * RateDiagnosticDialog — in-UI diagnostic for routes missing strategy Rate.
 *
 * Replaces the former console.table + window.alert pair with a structured dialog:
 *   - Summary header (total / missing / partial pairs)
 *   - Broker/Strategy group table with expandable rows showing affected routes
 *   - "Mixed" groups (some routes rated, some not) are highlighted as likely
 *     subscription-layer gaps
 *   - Manual refresh button
 */

import { useEffect, useMemo, useState, Fragment } from 'react';
import { Loader2, AlertTriangle, CheckCircle2, ChevronRight, ChevronDown, RefreshCw } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { apiService } from '@/services/api';

interface DiagnosticRoute {
  sequence: number;
  routeId: number;
  ticker?: string;
  status?: string;
  broker?: string;
  strategyType?: string;
  strategyStyle?: string;
  /** EMSX_STRATEGY_PART_RATE1 (backend returns as `rate1`). */
  rate1?: number | string | null;
  /** EMSX_STRATEGY_PART_RATE2 (backend returns as `rate2`). */
  rate2?: number | string | null;
  hasRate?: boolean;
}

interface DiagnosticGroup {
  broker: string;
  strategyType: string;
  total: number;
  withRate: number;
  withoutRate: number;
  routes: DiagnosticRoute[];
}

interface DiagnosticSummary {
  totalRoutesWithStrategy: number;
  routesWithRate: number;
  routesMissingRate: number;
  brokerStrategyPairsFullyMissing: number;
  brokerStrategyPairsPartiallyMissing: number;
}

interface DiagnosticData {
  summary: DiagnosticSummary;
  groups: DiagnosticGroup[];
}

interface RateDiagnosticDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

type GroupStatus = 'ok' | 'partial' | 'missing';

const classifyGroup = (g: DiagnosticGroup): GroupStatus => {
  if (g.withoutRate === 0) return 'ok';
  if (g.withRate === 0) return 'missing';
  return 'partial';
};

export function RateDiagnosticDialog({ open, onOpenChange }: RateDiagnosticDialogProps) {
  const [data, setData] = useState<DiagnosticData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [showOnlyIssues, setShowOnlyIssues] = useState(true);

  const runDiagnostic = async () => {
    setLoading(true);
    setError('');
    try {
      const res = await apiService.diagnoseStrategyRate();
      if (res.success && res.data) {
        setData(res.data as DiagnosticData);
        // Auto-expand partial/missing groups for immediate visibility
        const autoExpand = new Set<string>();
        (res.data as DiagnosticData).groups.forEach(g => {
          if (classifyGroup(g) !== 'ok') autoExpand.add(`${g.broker}|${g.strategyType}`);
        });
        setExpanded(autoExpand);
      } else {
        setError(res.error || 'Diagnostic request failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (open && !data && !loading) void runDiagnostic();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const visibleGroups = useMemo(() => {
    if (!data) return [];
    const sorted = [...data.groups].sort((a, b) => {
      const rank: Record<GroupStatus, number> = { missing: 0, partial: 1, ok: 2 };
      return rank[classifyGroup(a)] - rank[classifyGroup(b)];
    });
    return showOnlyIssues ? sorted.filter(g => classifyGroup(g) !== 'ok') : sorted;
  }, [data, showOnlyIssues]);

  const toggle = (key: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Strategy Rate Diagnostic</DialogTitle>
          <DialogDescription>
            Groups active routes by (broker, strategy) and checks whether each strategy's
            <code className="mx-1 px-1 bg-muted rounded text-xs">EMSX_STRATEGY_PART_RATE1/2</code>
            field is populated. Mixed groups indicate a likely subscription-layer gap.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {/* Summary */}
          {data && (
            <div className="grid grid-cols-5 gap-2 text-xs">
              <StatCard label="Routes w/ Strategy" value={data.summary.totalRoutesWithStrategy} />
              <StatCard label="With Rate" value={data.summary.routesWithRate} tone="ok" />
              <StatCard label="Missing Rate" value={data.summary.routesMissingRate}
                tone={data.summary.routesMissingRate > 0 ? 'warn' : 'ok'} />
              <StatCard label="Pairs Fully Missing" value={data.summary.brokerStrategyPairsFullyMissing}
                tone={data.summary.brokerStrategyPairsFullyMissing > 0 ? 'warn' : 'ok'} />
              <StatCard label="Pairs Partially Missing" value={data.summary.brokerStrategyPairsPartiallyMissing}
                tone={data.summary.brokerStrategyPairsPartiallyMissing > 0 ? 'warn' : 'ok'} />
            </div>
          )}

          {/* Toolbar */}
          <div className="flex items-center gap-3 text-xs">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={showOnlyIssues} onChange={(e) => setShowOnlyIssues(e.target.checked)} />
              Only show problematic groups
            </label>
            <button onClick={runDiagnostic} disabled={loading}
              className="ml-auto flex items-center gap-1 px-2 py-0.5 border border-border rounded hover:bg-secondary disabled:opacity-50">
              <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
              Re-run
            </button>
          </div>

          {loading && !data && (
            <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
              <Loader2 className="h-5 w-5 animate-spin mr-2" /> Running diagnostic…
            </div>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}

          {/* Groups table */}
          {data && (
            <div className="border border-border rounded">
              <table className="w-full text-xs">
                <thead className="bg-secondary/50">
                  <tr>
                    <th className="w-6"></th>
                    <th className="text-left px-2 py-1">Broker</th>
                    <th className="text-left px-2 py-1">Strategy</th>
                    <th className="text-right px-2 py-1">With Rate</th>
                    <th className="text-right px-2 py-1">Missing</th>
                    <th className="text-right px-2 py-1">Total</th>
                    <th className="text-left px-2 py-1">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleGroups.length === 0 ? (
                    <tr><td colSpan={7} className="text-center py-4 text-muted-foreground">
                      {showOnlyIssues && data.groups.length > 0
                        ? 'All groups have Rate populated. ✓'
                        : 'No routes with strategies found.'}
                    </td></tr>
                  ) : (
                    visibleGroups.map(g => {
                      const key = `${g.broker}|${g.strategyType}`;
                      const isOpen = expanded.has(key);
                      const status = classifyGroup(g);
                      return (
                        <Fragment key={key}>
                          <tr className="border-t border-border/50 hover:bg-muted/30 cursor-pointer"
                            onClick={() => toggle(key)}>
                            <td className="px-1 text-center">
                              {isOpen ? <ChevronDown className="h-3 w-3 inline" /> : <ChevronRight className="h-3 w-3 inline" />}
                            </td>
                            <td className="px-2 py-1 font-mono">{g.broker}</td>
                            <td className="px-2 py-1">{g.strategyType}</td>
                            <td className="px-2 py-1 text-right font-mono-numbers">{g.withRate}</td>
                            <td className={`px-2 py-1 text-right font-mono-numbers ${g.withoutRate > 0 ? 'text-destructive font-semibold' : ''}`}>
                              {g.withoutRate}
                            </td>
                            <td className="px-2 py-1 text-right font-mono-numbers">{g.total}</td>
                            <td className="px-2 py-1"><StatusBadge status={status} /></td>
                          </tr>
                          {isOpen && (
                            <tr>
                              <td colSpan={7} className="px-2 py-1 bg-muted/20">
                                <table className="w-full text-[11px]">
                                  <thead>
                                    <tr className="text-muted-foreground">
                                      <th className="text-left py-0.5">Route</th>
                                      <th className="text-left py-0.5">Ticker</th>
                                      <th className="text-left py-0.5">Status</th>
                                      <th className="text-right py-0.5">Rate1</th>
                                      <th className="text-right py-0.5">Rate2</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {g.routes.map((r, i) => {
                                      const missing = !(r.hasRate ?? ((r.rate1 != null && r.rate1 !== '') || (r.rate2 != null && r.rate2 !== '')));
                                      return (
                                        <tr key={i} className={missing ? 'text-destructive' : ''}>
                                          <td className="py-0.5 font-mono">{r.sequence}.{r.routeId}</td>
                                          <td className="py-0.5">{r.ticker || '-'}</td>
                                          <td className="py-0.5">{r.status || '-'}</td>
                                          <td className="py-0.5 text-right font-mono">{r.rate1 ?? '∅'}</td>
                                          <td className="py-0.5 text-right font-mono">{r.rate2 ?? '∅'}</td>
                                        </tr>
                                      );
                                    })}
                                  </tbody>
                                </table>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          )}

          {data && data.summary.brokerStrategyPairsPartiallyMissing > 0 && (
            <p className="text-xs text-amber-700 dark:text-amber-300 flex items-start gap-1.5">
              <AlertTriangle className="h-3.5 w-3.5 mt-0.5 flex-shrink-0" />
              Partially-missing pairs suggest Bloomberg did not push <code className="mx-1 px-1 bg-muted rounded">PART_RATE1/2</code>
              for some routes. Verify the subscription fields include these and that the broker strategy was active when the route was created.
            </p>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function StatCard({ label, value, tone }: { label: string; value: number; tone?: 'ok' | 'warn' }) {
  const toneClass = tone === 'warn'
    ? 'border-destructive/40 bg-destructive/5 text-destructive'
    : tone === 'ok'
    ? 'border-emerald-500/30 bg-emerald-500/5 text-emerald-700 dark:text-emerald-300'
    : 'border-border bg-secondary/30';
  return (
    <div className={`border rounded p-2 ${toneClass}`}>
      <div className="text-[10px] uppercase tracking-wide opacity-80">{label}</div>
      <div className="text-lg font-semibold font-mono-numbers">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: GroupStatus }) {
  if (status === 'ok') {
    return <span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-300">
      <CheckCircle2 className="h-3 w-3" /> OK
    </span>;
  }
  if (status === 'partial') {
    return <span className="inline-flex items-center gap-1 text-amber-700 dark:text-amber-300">
      <AlertTriangle className="h-3 w-3" /> Partial
    </span>;
  }
  return <span className="inline-flex items-center gap-1 text-destructive">
    <AlertTriangle className="h-3 w-3" /> Missing
  </span>;
}
