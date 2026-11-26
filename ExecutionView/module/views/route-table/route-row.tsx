/** Route table row (A14/229). Extracted verbatim from RouteTable.tsx. */

import { formatNumber, formatInt, getSideClass } from '@shared/lib/format-utils';
import { RouteActionMenu } from '@execution/components/route-action-menu';
import type { Route } from '@execution/types';
import { getPercentFilled, getRouteStrategyDetail } from './helpers';
import { getStatusBadge } from './status-badge';

interface RouteTableRowProps {
  route: Route;
  effectiveRoute: Route;
  currentTrader: string;
  selected: boolean;
  onToggleSelection: (routeId: string) => void;
  onCancel: (route: Route) => void;
  onModify: (route: Route) => void;
}

export const RouteTableRow = ({
  route,
  effectiveRoute,
  currentTrader,
  selected,
  onToggleSelection,
  onCancel,
  onModify,
}: RouteTableRowProps) => (
  <tr className={`border-b border-border/50 hover:bg-muted/50 transition-colors text-xs h-8 ${selected ? 'bg-primary/5' : ''}`}>
    {/* Selection checkbox */}
    <td className="px-2 text-center">
      <input
        type="checkbox"
        aria-label={`Select route ${route.sequence}.${route.routeId}`}
        checked={selected}
        onChange={() => onToggleSelection(route.id)}
        onClick={(e) => e.stopPropagation()}
      />
    </td>
    {/* Actions */}
    <td className="px-2">
      <RouteActionMenu
        route={effectiveRoute}
        currentTrader={currentTrader}
        onCancel={onCancel}
        onModify={onModify}
      />
    </td>
    {/* Order# */}
    <td className="px-2 font-mono text-muted-foreground">{route.sequence}</td>
    {/* Route# */}
    <td className="px-2 font-mono text-xs">{route.routeId}</td>
    {/* Ticker */}
    <td className="px-2 font-semibold">{route.ticker || '-'}</td>
    {/* Exchange */}
    <td className="px-2 text-xs">{route.exchange || '-'}</td>
    {/* Side */}
    <td className={`px-2 font-semibold ${getSideClass(route.side)}`}>{route.side}</td>
    {/* Status */}
    <td className="px-2">{getStatusBadge(effectiveRoute.status)}</td>
    {/* Type */}
    <td className="px-2 text-muted-foreground">{route.orderType}</td>
    {/* Qty */}
    <td className="px-2 text-right font-mono-numbers">{formatInt(route.amount)}</td>
    {/* %Filled */}
    <td className="px-2 text-right font-mono-numbers text-xs">{getPercentFilled(route)}</td>
    {/* Filled */}
    <td className="px-2 text-right font-mono-numbers">{formatInt(route.filled)}</td>
    {/* Working */}
    <td className="px-2 text-right font-mono-numbers">{formatInt(route.working)}</td>
    {/* Avg Px */}
    <td className="px-2 text-right font-mono-numbers text-xs">{formatNumber(route.avgPrice)}</td>
    {/* Limit Px */}
    <td className="px-2 text-right font-mono-numbers">{formatNumber(route.limitPrice)}</td>
    {/* Last Px */}
    <td className="px-2 text-right font-mono-numbers text-xs text-muted-foreground">{formatNumber(route.lastPrice)}</td>
    {/* Last Shr */}
    <td className="px-2 text-right font-mono-numbers text-xs">{formatInt(route.lastShares)}</td>
    {/* Broker */}
    <td className="px-2 font-medium">{route.broker}</td>
    {/* Trader */}
    <td className="px-2 text-xs">{route.trader}</td>
    {/* Strategy */}
    <td className="px-2 text-xs" title={getRouteStrategyDetail(route)}>{route.strategyType}</td>
    {/* Strat Params */}
    <td className="px-2 text-xs text-muted-foreground truncate max-w-[120px]" title={getRouteStrategyDetail(route)}>{getRouteStrategyDetail(route)}</td>
    {/* Slice */}
    <td className="px-2 text-center text-xs font-mono-numbers">{route.sliceIndex != null ? `#${route.sliceIndex}` : ''}</td>
    {/* Slice Status */}
    <td className="px-2 text-xs">{route.sliceStatus || ''}</td>
    {/* Schedule */}
    <td className="px-2 text-xs text-muted-foreground font-mono-numbers">
      {route.scheduledStart ? new Date(route.scheduledStart).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
      {route.scheduledStart && route.scheduledEnd ? '–' : ''}
      {route.scheduledEnd ? new Date(route.scheduledEnd).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
    </td>
    {/* Notes */}
    <td className="px-2 text-xs text-muted-foreground truncate max-w-[120px]" title={route.notes}>{route.notes}</td>
    {/* Reason */}
    <td className="px-2 text-xs text-muted-foreground">{route.reasonDesc || route.reasonCode}</td>
  </tr>
);
