import { useMemo, useState, Fragment } from 'react';
import { ChevronDown, ChevronRight, Coffee } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { ScrollArea } from '@/components/ui/scroll-area';
import { fmtNum, fmtInt, fmtDollar } from '@shared/lib/format-utils';
import type { Order, OrderStatus } from '@execution/types'

// Statuses considered "active" — orders with these are excluded from the lazy board
const ACTIVE_STATUSES = new Set<OrderStatus>([
  'WORKING', 'QUEUED', 'COMPLETED', 'FILLED', 'SUSPENDED',
]);

function getStatusBadge(status: OrderStatus) {
  const map: Record<string, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }> = {
    NEW:            { variant: 'outline' },
    ASSIGN:         { variant: 'outline', className: 'border-cyan-500 text-cyan-600' },
    PARTIAL:        { variant: 'default', className: 'bg-amber-500/90 hover:bg-amber-600' },
    CANCELLED:      { variant: 'secondary' },
    PENDING_CANCEL: { variant: 'destructive', className: 'bg-red-400/90' },
    REJECTED:       { variant: 'destructive' },
    SENT:           { variant: 'default', className: 'bg-sky-500/90 hover:bg-sky-600' },
  };
  const s = map[status] ?? { variant: 'outline' as const };
  return <Badge variant={s.variant} className={`text-[10px] px-1.5 py-0 leading-4 ${s.className ?? ''}`}>{status}</Badge>;
}

interface LazyOrderBoardProps {
  allOrders: Order[];
  isLoading: boolean;
}

export function LazyOrderBoard({ allOrders, isLoading }: LazyOrderBoardProps) {
  const [expandedExchanges, setExpandedExchanges] = useState<Set<string>>(() => new Set());

  // Filter to lazy orders (not in active statuses), group by exchange
  const { groups, total } = useMemo(() => {
    const lazy = allOrders.filter(o => !ACTIVE_STATUSES.has(o.status));
    const map = new Map<string, Order[]>();
    for (const o of lazy) {
      const ex = o.exchange || '(No Exchange)';
      if (!map.has(ex)) map.set(ex, []);
      map.get(ex)!.push(o);
    }
    const sorted = Array.from(map.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([exchange, orders]) => ({ exchange, orders }));
    return { groups: sorted, total: lazy.length };
  }, [allOrders]);

  const toggleExchange = (exchange: string) => {
    setExpandedExchanges(prev => {
      const next = new Set(prev);
      if (next.has(exchange)) next.delete(exchange); else next.add(exchange);
      return next;
    });
  };

  return (
    <div className="rounded-lg border border-border bg-card">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <Coffee className="h-4 w-4 text-orange-400" />
          <span className="text-sm font-semibold">Lazy Order Board</span>
          <Badge variant="secondary" className="text-xs">{total} orders</Badge>
        </div>
        <span className="text-[11px] text-muted-foreground">
          Excludes: WORKING, QUEUED, COMPLETED, FILLED, SUSPENDED
        </span>
      </div>

      {/* Table */}
      <ScrollArea className="max-h-[360px]">
        <table className="w-full min-w-max text-xs">
          <thead className="sticky top-0 bg-card z-10 border-b border-border">
            <tr>
              {['Order ID', 'Ticker', 'Side', 'Status', 'Type', 'Qty', '%Filled', 'Limit Px', 'Avg Px', '$Value', 'Broker', 'Portfolio', 'Trader', 'Created'].map(h => (
                <th key={h} className="px-2 py-1.5 text-left text-[11px] font-semibold text-muted-foreground uppercase tracking-wider whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading && total === 0 && (
              <tr><td colSpan={14} className="py-8 text-center text-muted-foreground">Loading…</td></tr>
            )}
            {!isLoading && total === 0 && (
              <tr><td colSpan={14} className="py-8 text-center text-muted-foreground">No lazy orders — all orders are active</td></tr>
            )}

            {groups.map(({ exchange, orders }) => {
              const isExpanded = expandedExchanges.has(exchange);
              return (
                <Fragment key={exchange}>
                  <tr
                    className="cursor-pointer select-none hover:bg-muted/40 transition-colors"
                    onClick={() => toggleExchange(exchange)}
                  >
                    <td colSpan={14} className="px-3 py-1.5 bg-muted/20">
                      <div className="flex items-center gap-2">
                        {isExpanded
                          ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                          : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                        <span className="font-semibold text-xs">{exchange}</span>
                        <Badge variant="outline" className="text-[10px]">{orders.length}</Badge>
                      </div>
                    </td>
                  </tr>
                  {isExpanded && orders.map(order => (
                    <tr key={order.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors">
                      <td className="px-2 py-1.5 font-mono text-xs">{order.id}</td>
                      <td className="px-2 py-1.5 font-mono font-medium whitespace-nowrap">{order.symbol}</td>
                      <td className={`px-2 py-1.5 font-medium ${order.side === 'BUY' ? 'text-green-400' : 'text-red-400'}`}>{order.side}</td>
                      <td className="px-2 py-1.5">{getStatusBadge(order.status)}</td>
                      <td className="px-2 py-1.5 text-muted-foreground">{order.orderType}</td>
                      <td className={`px-2 py-1.5 text-right font-mono ${order.side === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>
                        {fmtInt(order.quantity)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono">
                        {order.quantity > 0 ? order.percentFilled.toFixed(0) + '%' : ''}
                      </td>
                      <td className="px-2 py-1.5 text-right font-mono">{order.price != null ? fmtNum(order.price) : '—'}</td>
                      <td className="px-2 py-1.5 text-right font-mono">{fmtNum(order.avgPrice)}</td>
                      <td className="px-2 py-1.5 text-right font-mono">
                        {order.dollarValueUsd != null ? fmtDollar(order.dollarValueUsd) : '—'}
                      </td>
                      <td className="px-2 py-1.5">{order.broker}</td>
                      <td className="px-2 py-1.5 truncate max-w-[100px]">{order.portfolio}</td>
                      <td className="px-2 py-1.5">{order.trader}</td>
                      <td className="px-2 py-1.5 text-muted-foreground whitespace-nowrap">
                        {new Date(order.createdAt).toLocaleString('en-US', { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </td>
                    </tr>
                  ))}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </ScrollArea>
    </div>
  );
}