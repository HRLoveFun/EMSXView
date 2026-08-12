import { useMemo } from 'react';
import { CheckCircle2 } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { ViolationList } from '@execution/components/compliance-violation';
import type { Violation } from '@execution/types';
import type { AllocStatus, OrderRowProps } from './types';

export function OrderRow(p: OrderRowProps) {
  const { order: o, row: r, lot, total, effectiveRemaining, routedAmount,
    overAlloc, anyAlloc, selectedBrokers, isBrokerAllowedFor,
    onPatchRow, onPatchAlloc, editable, phase, ratios } = p;

  const aggregateStatus: AllocStatus | undefined = useMemo(() => {
    const statuses = Object.values(r.allocations).map(a => a.status).filter(Boolean) as AllocStatus[];
    if (statuses.length === 0) return undefined;
    if (statuses.includes('BLOCKED')) return 'BLOCKED';
    if (statuses.includes('FAILED')) return 'FAILED';
    if (statuses.every(s => s === 'SUCCESS')) return 'SUCCESS';
    return undefined;
  }, [r.allocations]);

  const aggregateViolations: Violation[] = useMemo(() => {
    const seen = new Set<string>();
    const out: Violation[] = [];
    for (const a of Object.values(r.allocations)) {
      for (const v of a.violations ?? []) {
        const key = (v as { code?: string; message?: string }).code
          || (v as { message?: string }).message
          || JSON.stringify(v);
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(v);
      }
    }
    return out;
  }, [r.allocations]);

  return (
    <tr className="border-t border-border">
      <td className="text-center">
        <Checkbox
          checked={r.selected}
          onCheckedChange={(v) => onPatchRow({ selected: !!v })}
          disabled={phase === 'submitting' || phase === 'result'}
        />
      </td>
      <td className="px-2 py-1 font-mono">{o.id}</td>
      <td className="px-2 py-1">{o.symbol}</td>
      <td className={`px-2 py-1 font-semibold ${o.side === 'BUY' ? 'text-green-600' : 'text-red-600'}`}>{o.side}</td>
      <td className="px-2 py-1 text-[11px] text-muted-foreground">{o.orderType}</td>
      <td className="px-2 py-1 text-right font-mono-numbers">
        {o.price != null ? o.price.toFixed(2) : '\u2014'}
      </td>
      <td className="px-2 py-1 text-right font-mono-numbers">
        {effectiveRemaining.toLocaleString()}
        <div className="text-[10px] text-muted-foreground/70">
          {routedAmount > 0
            ? `\u2212${routedAmount.toLocaleString()} routed \u00b7 idle ${effectiveRemaining.toLocaleString()}`
            : `idle ${effectiveRemaining.toLocaleString()}`}
        </div>
      </td>
      {selectedBrokers.map(b => {
        const a = r.allocations[b];
        const q = a ? parseInt(a.qty || '0', 10) : 0;
        const allowed = isBrokerAllowedFor(b, o);
        const oddLot = q > 0 && lot > 1 && q % lot !== 0;
        const cellInvalid = oddLot || (overAlloc && q > 0);
        const allocStatus = a?.status;
        return (
          <td key={b} className="px-2 py-1 text-right">
            {allowed ? (
              <div className="inline-flex flex-col items-end gap-0">
                <Input
                  type="number"
                  min={0}
                  step={lot}
                  value={a?.qty ?? '0'}
                  onChange={(e) => onPatchAlloc(b, { qty: e.target.value })}
                  onWheel={e => e.currentTarget.blur()}
                  className={
                    'h-7 w-24 text-right font-mono text-xs ' +
                    (cellInvalid
                      ? 'ring-2 ring-red-500/70 ring-inset'
                      : (allocStatus === 'SUCCESS'
                        ? (phase === 'review'
                          ? 'ring-2 ring-emerald-500/40 ring-inset ring-dashed'
                          : 'ring-2 ring-emerald-500/40 ring-inset')
                        : (allocStatus === 'BLOCKED'
                          ? (phase === 'review'
                            ? 'ring-2 ring-red-500/40 ring-inset ring-dashed'
                            : 'ring-2 ring-red-500/40 ring-inset')
                          : (allocStatus === 'FAILED'
                            ? 'ring-2 ring-amber-500/40 ring-inset'
                            : ''))))
                  }
                  disabled={!editable}
                  placeholder="0"
                  title={oddLot ? `Odd lot \u2014 must be a multiple of ${lot}` : undefined}
                />
                {q > 0 && effectiveRemaining > 0 && (() => {
                  const actualPct = Math.round(q / effectiveRemaining * 1000) / 10;
                  const targetPct = ratios[b] ?? 0;
                  const deviated = targetPct > 0 && Math.abs(actualPct - targetPct) > 2;
                  return (
                    <span className={`text-[10px] font-mono ${deviated ? 'text-red-500 font-semibold' : 'text-muted-foreground/60'}`}>
                      {actualPct}%
                    </span>
                  );
                })()}
              </div>
            ) : (
              <span className="text-[10px] text-muted-foreground italic" title="Broker not allowed for this order's market in Settings \u2192 Market Broker Mapping">
                n/a
              </span>
            )}
          </td>
        );
      })}
      <td className={'px-2 py-1 text-right font-mono-numbers ' + (overAlloc ? 'text-red-600 font-semibold' : '')}>
        {total.toLocaleString()}{overAlloc ? ' \u26a0' : ''}
        {effectiveRemaining > 0 && (
          <div className="text-[10px] text-muted-foreground/70">
            {Math.round((total / effectiveRemaining) * 100)}% of avail
          </div>
        )}
      </td>
      <td className="px-2 py-1">
        {aggregateStatus === 'SUCCESS' && (
          <>
            <span className="text-emerald-600 inline-flex items-center gap-1">
              <CheckCircle2 className="h-3 w-3" />Routed
            </span>
            {aggregateViolations.length > 0 && (
              <div className="mt-0.5">
                <ViolationList violations={aggregateViolations} />
              </div>
            )}
          </>
        )}
        {aggregateStatus === 'BLOCKED' && <ViolationList violations={aggregateViolations} />}
        {aggregateStatus === 'FAILED' && <span className="text-amber-600 text-xs">Some failed</span>}
        {!aggregateStatus && overAlloc && (
          <span className="text-red-600 text-[11px]">Over-allocated</span>
        )}
        {!aggregateStatus && !overAlloc && !anyAlloc && selectedBrokers.length > 0 && (
          <span className="text-muted-foreground text-[11px]">No qty allocated</span>
        )}
      </td>
    </tr>
  );
}
