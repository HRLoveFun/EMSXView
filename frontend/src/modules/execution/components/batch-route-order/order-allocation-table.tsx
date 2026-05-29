import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { OrderRow } from './order-row';
import { lotSizeOf } from './utils';
import { QUICK_PCT_PRESETS } from './types';
import type { OrderAllocationTableProps } from './types';

export function OrderAllocationTable({
  orders,
  rows,
  selectedBrokers,
  editable,
  phase,
  ratios,
  effectiveRemainingOf,
  pendingWorkingByOrder,
  isBrokerAllowedFor,
  patchRow,
  patchAlloc,
  applyPercentToBroker,
}: OrderAllocationTableProps) {
  const computeAllocQty = (a: { qty: string } | undefined): number => {
    if (!a || a.qty === '') return 0;
    const q = parseInt(a.qty, 10);
    return Number.isFinite(q) && q > 0 ? q : 0;
  };

  const rowTotalQty = (r: typeof rows[string]): number =>
    Object.values(r.allocations).reduce((acc, a) => acc + computeAllocQty(a), 0);

  return (
    <div className="border border-border rounded overflow-hidden">
      <div className="max-h-[50vh] overflow-y-auto">
        <table className="w-full text-xs">
          <thead className="bg-secondary/50 sticky top-0 z-10">
            <tr>
              <th className="w-8 text-center"></th>
              <th className="text-left px-2 py-1">Order</th>
              <th className="text-left px-2 py-1">Ticker</th>
              <th className="text-left px-2 py-1">Side</th>
              <th className="text-left px-2 py-1">Type</th>
              <th className="text-right px-2 py-1">Price</th>
              <th className="text-right px-2 py-1">Remain</th>
              {selectedBrokers.map(b => (
                <th key={b} className="text-right px-2 py-1 font-mono">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        disabled={!editable}
                        className="inline-flex items-center gap-1 hover:text-primary disabled:opacity-60 disabled:cursor-not-allowed"
                        title={`Quick-fill ${b} column with % of each selected order's effective remaining`}
                      >
                        {b}
                        <span className="text-[9px] text-muted-foreground/70">{'\u25BE'}</span>
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="text-xs">
                      {QUICK_PCT_PRESETS.map(pct => (
                        <DropdownMenuItem
                          key={pct}
                          onSelect={() => applyPercentToBroker(b, pct)}
                        >
                          Set {b} = {pct}% of remain
                        </DropdownMenuItem>
                      ))}
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        onSelect={() => applyPercentToBroker(b, 0)}
                        disabled
                      >
                        Custom % \u2014 use toolbar input
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </th>
              ))}
              <th className="text-right px-2 py-1">{'\u03A3'} Qty</th>
              <th className="text-left px-2 py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {orders.length === 0 && (
              <tr><td colSpan={8 + selectedBrokers.length} className="text-center py-6 text-muted-foreground">
                No orders.
              </td></tr>
            )}
            {orders.map(o => {
              const r = rows[o.id];
              if (!r) return null;
              const lot = lotSizeOf(o);
              const total = rowTotalQty(r);
              const effRemain = effectiveRemainingOf(o);
              const pendingWorking = pendingWorkingByOrder[o.id] ?? 0;
              const overAlloc = total > effRemain;
              const anyAlloc = Object.values(r.allocations).some(a => computeAllocQty(a) > 0);
              return (
                <OrderRow
                  key={o.id}
                  order={o}
                  row={r}
                  lot={lot}
                  total={total}
                  effectiveRemaining={effRemain}
                  pendingWorking={pendingWorking}
                  overAlloc={overAlloc}
                  anyAlloc={anyAlloc}
                  selectedBrokers={selectedBrokers}
                  isBrokerAllowedFor={isBrokerAllowedFor}
                  onPatchRow={(patch) => patchRow(o.id, patch)}
                  onPatchAlloc={(b, patch) => patchAlloc(o.id, b, patch)}
                  editable={editable}
                  phase={phase}
                  ratios={ratios}
                />
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
