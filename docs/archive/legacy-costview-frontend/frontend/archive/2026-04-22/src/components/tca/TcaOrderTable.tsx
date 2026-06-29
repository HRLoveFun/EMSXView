/**
 * TcaOrderTable — paginated order summary table.
 *
 * Each row is collapsible to reveal route-level details via TcaRouteTable.
 * Clicking the row header selects the order for chart display.
 */

import { useState } from 'react';
import type { TcaOrderSummary, TcaReport } from '@/services/tca-api';
import { TcaRouteTable } from './TcaRouteTable';

interface TcaOrderTableProps {
  report: TcaReport;
  onPageChange: (offset: number) => void;
  onSelectOrder: (order: TcaOrderSummary | null) => void;
  selectedOrderId: string | null;
}

function fmt(v: number | null | undefined, decimals = 2): string {
  if (v == null) return '—';
  return v.toFixed(decimals);
}

function fmtBps(v: number | null | undefined): string {
  if (v == null) return '—';
  const sign = v > 0 ? '+' : '';
  return `${sign}${v.toFixed(1)} bps`;
}

export function TcaOrderTable({
  report,
  onPageChange,
  onSelectOrder,
  selectedOrderId,
}: TcaOrderTableProps) {
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

  const { orders, total_orders, offset, limit } = report;

  const totalPages = Math.ceil(total_orders / limit);
  const currentPage = Math.floor(offset / limit) + 1;

  function toggleExpand(orderId: string) {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(orderId)) {
        next.delete(orderId);
      } else {
        next.add(orderId);
      }
      return next;
    });
  }

  function handleRowClick(order: TcaOrderSummary) {
    if (selectedOrderId === order.order_id) {
      onSelectOrder(null);
    } else {
      onSelectOrder(order);
    }
  }

  if (orders.length === 0) {
    return (
      <div className="bg-card border border-border rounded-lg p-6 text-center text-muted-foreground text-sm">
        No orders matched the given filters.
      </div>
    );
  }

  return (
    <div className="bg-card border border-border rounded-lg overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-separate border-spacing-0">
          <thead className="bg-muted/50">
            <tr className="text-muted-foreground text-xs">
              <th className="text-left px-3 py-2 font-medium w-6"></th>
              <th className="text-left px-3 py-2 font-medium">Order ID</th>
              <th className="text-left px-3 py-2 font-medium">Date</th>
              <th className="text-left px-3 py-2 font-medium">Symbol</th>
              <th className="text-left px-3 py-2 font-medium">Side</th>
              <th className="text-left px-3 py-2 font-medium">Algo</th>
              <th className="text-right px-3 py-2 font-medium">Fill %</th>
              <th className="text-right px-3 py-2 font-medium">Exec Price</th>
              <th className="text-right px-3 py-2 font-medium">VWAP</th>
              <th className="text-right px-3 py-2 font-medium">Tracking Error</th>
              <th className="text-right px-3 py-2 font-medium">Vol % ADV20</th>
              <th className="text-right px-3 py-2 font-medium">Volatility</th>
              <th className="text-right px-3 py-2 font-medium">Price Move</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order) => {
              const isExpanded = expandedIds.has(order.order_id);
              const isSelected = selectedOrderId === order.order_id;
              const teBps = order.tracking_error_bps;
              const teColor =
                teBps == null
                  ? ''
                  : teBps < -10
                  ? 'text-green-500'
                  : teBps > 10
                  ? 'text-red-500'
                  : '';

              return (
                <>
                  <tr
                    key={order.order_id}
                    className={`border-t border-border hover:bg-muted/40 cursor-pointer transition-colors ${
                      isSelected ? 'bg-primary/10' : ''
                    }`}
                    onClick={() => handleRowClick(order)}
                  >
                    {/* Expand toggle */}
                    <td className="px-3 py-2">
                      <button
                        className="text-muted-foreground hover:text-foreground transition-colors"
                        onClick={(e) => {
                          e.stopPropagation();
                          toggleExpand(order.order_id);
                        }}
                        aria-label={isExpanded ? 'Collapse routes' : 'Expand routes'}
                      >
                        {isExpanded ? '▾' : '▸'}
                      </button>
                    </td>
                    <td className="px-3 py-2 font-mono text-xs">{order.order_id}</td>
                    <td className="px-3 py-2 text-xs">{order.order_as_of_date}</td>
                    <td className="px-3 py-2 max-w-[140px] truncate" title={order.equ_ticker ?? ''}>
                      {order.equ_ticker ?? '—'}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={`text-xs font-medium ${
                          order.side?.toLowerCase() === 'buy'
                            ? 'text-green-500'
                            : order.side?.toLowerCase() === 'sell'
                            ? 'text-red-500'
                            : ''
                        }`}
                      >
                        {order.side ?? '—'}
                      </span>
                    </td>
                    <td className="px-3 py-2">{order.algo ?? '—'}</td>
                    <td className="px-3 py-2 text-right">{fmt(order.fill_pct, 1)}%</td>
                    <td className="px-3 py-2 text-right">{fmt(order.exec_price)}</td>
                    <td className="px-3 py-2 text-right">{fmt(order.interval_vwap)}</td>
                    <td className={`px-3 py-2 text-right ${teColor}`}>
                      {fmtBps(order.tracking_error_bps)}
                    </td>
                    <td className="px-3 py-2 text-right">{fmt(order.volume_pct_adv20, 2)}%</td>
                    <td className="px-3 py-2 text-right">{fmt(order.intraday_volatility, 2)}%</td>
                    <td className="px-3 py-2 text-right">{fmt(order.price_movement_pct, 2)}%</td>
                  </tr>

                  {isExpanded && (
                    <tr key={`${order.order_id}-routes`} className="bg-muted/20">
                      <td colSpan={13} className="p-0">
                        <TcaRouteTable routes={order.routes} />
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-border text-xs text-muted-foreground">
          <span>
            {offset + 1}–{Math.min(offset + limit, total_orders)} of {total_orders} orders
          </span>
          <div className="flex gap-1">
            <button
              disabled={currentPage === 1}
              onClick={() => onPageChange(Math.max(0, offset - limit))}
              className="px-2 py-0.5 rounded border border-border disabled:opacity-40 hover:bg-muted transition-colors"
            >
              ‹ Prev
            </button>
            <span className="px-2 py-0.5">
              {currentPage}/{totalPages}
            </span>
            <button
              disabled={currentPage === totalPages}
              onClick={() => onPageChange(offset + limit)}
              className="px-2 py-0.5 rounded border border-border disabled:opacity-40 hover:bg-muted transition-colors"
            >
              Next ›
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
