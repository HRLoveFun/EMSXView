import { useState, useCallback, useMemo, useEffect, useRef, Fragment } from 'react';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  Clock,
  CheckCircle2,
  XCircle,
  MinusCircle,
  AlertCircle,
  Layers,
  ChevronDown,
  ChevronRight,
  Filter,
  Search,
  X,
  RotateCcw,
  Loader2,
} from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Checkbox } from '@/components/ui/checkbox';
import { TooltipProvider } from '@/components/ui/tooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatNumber, formatInt, getSideClass } from '@/lib/format-utils';
import { ROUTE_GROUP_BY_OPTIONS, ROUTE_GROUP_BY_LABELS, type RouteGroupByValue } from '@/lib/table-constants';
import { RouteActionMenu } from '@/components/route-action-menu';
import {
  CancelRouteDialog,
} from '@/components/route-modify-dialogs';
import { UnifiedModifyRouteDialog } from '@/components/unified-modify-route-dialog';
import { RateDiagnosticDialog } from '@/components/rate-diagnostic-dialog';
import { BatchCancelDialog, BatchModifyDialog } from '@/components/batch-operation-dialogs';
import type { Route, CancelRouteRequest, ModifyRouteRequest } from '@/types';

type SortField = keyof Route | null;
type SortDirection = 'asc' | 'desc';
type GroupLevel = 'primary' | 'secondary';

interface RouteTableProps {
  routes: Route[];
  isLoading: boolean;
  currentTrader: string;
  onCancelRoute?: (request: CancelRouteRequest) => Promise<void>;
  onModifyRoute?: (request: ModifyRouteRequest) => Promise<void>;
  onRefresh?: () => Promise<void>;
}

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

interface GroupConfig {
  primary: RouteGroupByValue;
  secondary: RouteGroupByValue;
}

const TOTAL_COLS = 26; // 1 selection + 22 data columns + Slice + Slice Status + Schedule columns

export function RouteTable({ routes, isLoading, currentTrader, onCancelRoute, onModifyRoute, onRefresh }: RouteTableProps) {
  const [sortConfig, setSortConfig] = useState<SortConfig>({ field: 'sequence', direction: 'desc' });
  // Default: group by exchange, subgroup by ticker
  const [groupConfig, setGroupConfig] = useState<GroupConfig>({ primary: 'exchange', secondary: 'ticker' });
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [statusFilter, setStatusFilter] = useState<string[]>([]);
  const [statusFilterMode, setStatusFilterMode] = useState<'include' | 'exclude'>('include');
  const [brokerFilter, setBrokerFilter] = useState<string[]>([]);
  const [brokerFilterMode, setBrokerFilterMode] = useState<'include' | 'exclude'>('include');
  const [traderFilter, setTraderFilter] = useState<string[]>([]);
  const [traderFilterMode, setTraderFilterMode] = useState<'include' | 'exclude'>('include');
  const [tickerFilter, setTickerFilter] = useState('');

  // Optimistic "replacing" set — marked immediately after a modify is submitted so the
  // UI does not appear silently disabled during the brief window before Bloomberg pushes
  // the CXLRPRQ/CXLREP transition. Entries are cleared automatically once the route
  // reaches a stable status, or after a 6s safety timeout.
  const [replacingRouteIds, setReplacingRouteIds] = useState<Set<string>>(new Set());
  // Pending poll timers keyed by route id so we can cancel remaining polls once a
  // stable status has been observed. Avoids redundant REST calls after the route
  // is already settled.
  const pollTimersRef = useRef<Map<string, number[]>>(new Map());

  const cancelPollsFor = useCallback((routeId: string) => {
    const timers = pollTimersRef.current.get(routeId);
    if (timers) {
      timers.forEach(id => window.clearTimeout(id));
      pollTimersRef.current.delete(routeId);
    }
  }, []);

  const markReplacing = useCallback((routeId: string) => {
    setReplacingRouteIds(prev => {
      const next = new Set(prev);
      next.add(routeId);
      return next;
    });
    // Cancel any in-flight polls from a prior modify for the same route.
    cancelPollsFor(routeId);
    // Active polling — Bloomberg completes CxlRprQ -> CxlRep -> WORKING in ~200ms.
    // Schedule staged REST refreshes so the post-replace status appears within one
    // second. Each timer is tracked so we can stop the remaining polls the moment
    // the route reaches a stable status.
    const timers: number[] = [];
    [300, 900, 2000, 4000].forEach((delay) => {
      const id = window.setTimeout(() => {
        if (onRefresh) void onRefresh();
      }, delay);
      timers.push(id);
    });
    // Safety: drop the optimistic flag after 6s even if nothing cleared it.
    const safetyId = window.setTimeout(() => {
      setReplacingRouteIds(prev => {
        if (!prev.has(routeId)) return prev;
        const next = new Set(prev);
        next.delete(routeId);
        return next;
      });
      pollTimersRef.current.delete(routeId);
    }, 6000);
    timers.push(safetyId);
    pollTimersRef.current.set(routeId, timers);
  }, [onRefresh, cancelPollsFor]);

  // Auto-clear the optimistic flag once a route reaches a stable (non-transient)
  // status, AND cancel any remaining polls for that route.
  useEffect(() => {
    if (replacingRouteIds.size === 0) return;
    const stable = new Set(['WORKING', 'PARTFILL', 'PARTFILLED', 'FILLED', 'DONE', 'CANCEL', 'REJECTED', 'CXLREJ', 'CXLRPRJ']);
    const toClear: string[] = [];
    for (const r of routes) {
      if (replacingRouteIds.has(r.id) && stable.has(r.status)) toClear.push(r.id);
    }
    if (toClear.length === 0) return;
    toClear.forEach(id => cancelPollsFor(id));
    setReplacingRouteIds(prev => {
      const next = new Set(prev);
      toClear.forEach(id => next.delete(id));
      return next;
    });
  }, [routes, replacingRouteIds, cancelPollsFor]);

  // Cleanup timers on unmount to avoid leaks
  useEffect(() => {
    const pending = pollTimersRef.current;
    return () => {
      pending.forEach(timers => timers.forEach(id => window.clearTimeout(id)));
      pending.clear();
    };
  }, []);

  // Dialog states
  const [selectedRoute, setSelectedRoute] = useState<Route | null>(null);
  const [cancelDialogOpen, setCancelDialogOpen] = useState(false);
  const [modifyDialogOpen, setModifyDialogOpen] = useState(false);
  const [rateDiagnosticOpen, setRateDiagnosticOpen] = useState(false);

  // ---------- Batch selection ----------
  // A set of route.id for routes the user has checked for batch operations.
  const [selectedRouteIds, setSelectedRouteIds] = useState<Set<string>>(new Set());
  const [batchCancelOpen, setBatchCancelOpen] = useState(false);
  const [batchModifyOpen, setBatchModifyOpen] = useState(false);

  const toggleRouteSelection = useCallback((routeId: string) => {
    setSelectedRouteIds(prev => {
      const next = new Set(prev);
      if (next.has(routeId)) next.delete(routeId); else next.add(routeId);
      return next;
    });
  }, []);

  const clearSelection = useCallback(() => setSelectedRouteIds(new Set()), []);

  const toggleGroup = useCallback((key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleGroupByChange = useCallback((level: GroupLevel, value: RouteGroupByValue) => {
    setGroupConfig(prev => ({
      ...prev,
      [level]: value,
    }));
    setExpandedGroups(new Set());
  }, []);

  const handleSort = useCallback((field: SortField) => {
    setSortConfig(prev => ({
      field,
      direction: prev.field === field && prev.direction === 'asc' ? 'desc' : 'asc',
    }));
  }, []);

  // Filtered routes with include/exclude mode for status
  const filteredRoutes = useMemo(() => {
    let result = routes;
    if (statusFilter.length > 0) {
      if (statusFilterMode === 'include') {
        result = result.filter(r => statusFilter.includes(r.status));
      } else {
        // exclude mode
        result = result.filter(r => !statusFilter.includes(r.status));
      }
    }
    if (brokerFilter.length > 0) {
      if (brokerFilterMode === 'include') {
        result = result.filter(r => brokerFilter.includes(r.broker));
      } else {
        result = result.filter(r => !brokerFilter.includes(r.broker));
      }
    }
    if (traderFilter.length > 0) {
      if (traderFilterMode === 'include') {
        result = result.filter(r => traderFilter.includes(r.trader));
      } else {
        result = result.filter(r => !traderFilter.includes(r.trader));
      }
    }
    if (tickerFilter) {
      const t = tickerFilter.toUpperCase();
      result = result.filter(r => (r.ticker || '').toUpperCase().includes(t));
    }
    return result;
  }, [routes, statusFilter, statusFilterMode, brokerFilter, brokerFilterMode, traderFilter, traderFilterMode, tickerFilter]);

  const sortedRoutes = useMemo(() => {
    if (!sortConfig.field) return filteredRoutes;
    return [...filteredRoutes].sort((a, b) => {
      const field = sortConfig.field as keyof Route;
      const aValue = a[field];
      const bValue = b[field];
      const aNull = aValue === undefined || aValue === null || aValue === '';
      const bNull = bValue === undefined || bValue === null || bValue === '';
      if (aNull && bNull) return 0;
      if (aNull) return 1;
      if (bNull) return -1;
      if (typeof aValue === 'string' && typeof bValue === 'string') {
        return sortConfig.direction === 'asc' ? aValue.localeCompare(bValue) : bValue.localeCompare(aValue);
      }
      if (typeof aValue === 'number' && typeof bValue === 'number') {
        return sortConfig.direction === 'asc' ? aValue - bValue : bValue - aValue;
      }
      return 0;
    });
  }, [filteredRoutes, sortConfig]);

  // Two-level grouping
  const groupedRoutes = useMemo(() => {
    const { primary, secondary } = groupConfig;
    if (primary === 'none' && secondary === 'none') {
      return [{ key: '_all', routes: sortedRoutes, subGroups: null }];
    }
    
    const groups: Record<string, { routes: Route[]; subGroups: Record<string, Route[]> | null }> = {};
    
    for (const route of sortedRoutes) {
      const primaryKey = primary !== 'none'
        ? String(route[primary as keyof Route] || '(empty)')
        : '_all';
      
      if (!groups[primaryKey]) {
        groups[primaryKey] = { routes: [], subGroups: secondary !== 'none' ? {} : null };
      }
      
      if (secondary !== 'none' && primary !== 'none') {
        const secondaryKey = String(route[secondary as keyof Route] || '(empty)');
        if (!groups[primaryKey].subGroups![secondaryKey]) {
          groups[primaryKey].subGroups![secondaryKey] = [];
        }
        groups[primaryKey].subGroups![secondaryKey].push(route);
      } else {
        groups[primaryKey].routes.push(route);
      }
    }
    
    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, data]) => ({ 
        key, 
        routes: data.routes,
        subGroups: data.subGroups 
          ? Object.entries(data.subGroups)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([subKey, routes]) => ({ key: subKey, routes }))
          : null
      }));
  }, [sortedRoutes, groupConfig]);

  const getSortIcon = (field: SortField) => {
    if (sortConfig.field !== field) {
      return <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/50" />;
    }
    return sortConfig.direction === 'asc'
      ? <ArrowUp className="h-3.5 w-3.5 text-primary" />
      : <ArrowDown className="h-3.5 w-3.5 text-primary" />;
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'SENT':       return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />Sent</Badge>;
      case 'WORKING':    return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Working</Badge>;
      case 'PARTFILLED':
      case 'PARTFILL':   return <Badge variant="outline" className="status-badge status-partial gap-1"><MinusCircle className="h-3 w-3" />PartFill</Badge>;
      case 'FILLED':     return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Filled</Badge>;
      case 'CANCEL':     return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Cancel</Badge>;
      case 'CXLREQ':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />CxlReq</Badge>;
      case 'CXLREJ':     return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />CxlRej</Badge>;
      case 'CXLREP':     return <Badge variant="outline" className="status-badge status-working gap-1"><Loader2 className="h-3 w-3 animate-spin" />Replacing</Badge>;
      case 'CXLRPRQ':    return <Badge variant="outline" className="status-badge status-working gap-1"><Loader2 className="h-3 w-3 animate-spin" />Replacing</Badge>;
      case 'CXLRPRJ':    return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />CxlRprJ</Badge>;
      case 'REJECTED':   return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Rejected</Badge>;
      case 'DONE':       return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Done</Badge>;
      case 'QUEUED':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Queued</Badge>;
      case 'HOLD':       return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />Hold</Badge>;
      case 'BUST':       return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Bust</Badge>;
      case 'CORRECTED':  return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Corrected</Badge>;
      case 'REPPEN':     return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />RepPen</Badge>;
      case 'ROUTE-ERR':  return <Badge variant="outline" className="status-badge status-cancelled gap-1"><XCircle className="h-3 w-3" />Error</Badge>;
      case 'OMS-PEND':   return <Badge variant="outline" className="status-badge status-working gap-1"><Clock className="h-3 w-3" />OmsPend</Badge>;
      case 'A-SENT':     return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />A-Sent</Badge>;
      case 'ALLOCATED':  return <Badge variant="outline" className="status-badge status-filled gap-1"><CheckCircle2 className="h-3 w-3" />Allocated</Badge>;
      case 'OA-SENT':    return <Badge variant="outline" className="status-badge status-new gap-1"><AlertCircle className="h-3 w-3" />OA-Sent</Badge>;
      default:           return <Badge variant="outline" className="status-badge gap-1">{status}</Badge>;
    }
  };


  const hasActiveFilters = statusFilter.length > 0 || brokerFilter.length > 0 || traderFilter.length > 0 || !!tickerFilter;

  const getRouteStrategyDetail = (route: Route) => {
    if (!route.strategyType) return '';
    const parts: string[] = [];
    if (route.strategyPartRate1 != null) parts.push(`Rate: ${route.strategyPartRate1}%`);
    if (route.strategyPartRate2 != null) parts.push(`Rate2: ${route.strategyPartRate2}%`);
    if (route.strategyStyle) parts.push(`Style: ${route.strategyStyle}`);
    if (route.strategyStartTime) parts.push(`Start: ${route.strategyStartTime}`);
    if (route.strategyEndTime) parts.push(`End: ${route.strategyEndTime}`);
    return parts.join(' | ');
  };

  // Get unique values from current routes for filters
  const availableStatuses = useMemo(() => {
    const statuses = new Set(routes.map(r => r.status).filter(Boolean));
    return Array.from(statuses).sort();
  }, [routes]);

  const availableBrokers = useMemo(() => {
    const brokers = new Set(routes.map(r => r.broker).filter(Boolean));
    return Array.from(brokers).sort();
  }, [routes]);

  const availableTraders = useMemo(() => {
    const traders = new Set(routes.map(r => r.trader).filter(Boolean));
    return Array.from(traders).sort();
  }, [routes]);

  // Generic multi-select filter popover with include/exclude mode
  const multiSelectFilterPopover = (
    label: string,
    options: string[],
    selected: string[],
    setSelected: (vals: string[]) => void,
    mode: 'include' | 'exclude',
    setMode: (mode: 'include' | 'exclude') => void
  ) => {
    const active = selected.length > 0;
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button className={`inline-flex items-center ${active ? 'text-primary' : 'text-muted-foreground/50'}`}>
            <Filter className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-52 p-2" align="start">
          {/* Include/Exclude toggle */}
          <div className="flex items-center gap-1 mb-2 p-1 bg-secondary/50 rounded">
            <button
              className={`flex-1 text-xs py-1 px-2 rounded ${mode === 'include' ? 'bg-primary text-primary-foreground' : 'hover:bg-secondary'}`}
              onClick={() => setMode('include')}
            >
              Include
            </button>
            <button
              className={`flex-1 text-xs py-1 px-2 rounded ${mode === 'exclude' ? 'bg-destructive text-destructive-foreground' : 'hover:bg-secondary'}`}
              onClick={() => setMode('exclude')}
            >
              Exclude
            </button>
          </div>
          <div className="space-y-1 max-h-52 overflow-y-auto">
            {options.length === 0 ? (
              <div className="px-1 py-2 text-xs text-muted-foreground">No {label} available</div>
            ) : (
              options.map(opt => (
                <label key={opt} className="flex items-center gap-2 px-1 py-0.5 text-xs cursor-pointer hover:bg-accent rounded">
                  <Checkbox
                    checked={selected.includes(opt)}
                    onCheckedChange={(checked) => {
                      if (checked) setSelected([...selected, opt]);
                      else setSelected(selected.filter(x => x !== opt));
                    }}
                    className="h-3.5 w-3.5"
                  />
                  {opt}
                </label>
              ))
            )}
          </div>
          {active && (
            <button
              className="mt-2 w-full text-xs text-destructive hover:underline"
              onClick={() => setSelected([])}
            >Clear</button>
          )}
        </PopoverContent>
      </Popover>
    );
  };

  const textFilterPopover = (
    value: string,
    onChange: (v: string) => void,
    placeholder: string,
  ) => {
    const active = !!value;
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button className={`inline-flex items-center ${active ? 'text-primary' : 'text-muted-foreground/50'}`}>
            <Filter className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-44 p-2" align="start">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <Input
              value={value}
              onChange={e => onChange(e.target.value)}
              placeholder={placeholder}
              className="pl-7 h-7 text-xs"
              autoFocus
            />
            {active && (
              <button className="absolute right-2 top-1/2 -translate-y-1/2" onClick={() => onChange('')}>
                <X className="h-3 w-3 text-muted-foreground" />
              </button>
            )}
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  const getPercentFilled = (route: Route) => {
    if (route.amount <= 0) return '';
    return ((route.filled / route.amount) * 100).toFixed(0) + '%';
  };

  // Action handlers
  // Per-route in-flight guard: a user double-clicking "Cancel Route" while
  // the network is slow would otherwise dispatch the request twice. The
  // second call wastes a round-trip and emits a duplicate "already
  // cancelled" error toast. Treat the route as locked from submission
  // until either the parent refresh resolves or a 5s safety window expires.
  const inflightCancelRef = useRef<Set<string>>(new Set());
  const handleCancel = async (route: Route) => {
    if (!onCancelRoute) return;
    if (inflightCancelRef.current.has(route.id)) return;
    inflightCancelRef.current.add(route.id);
    const safety = window.setTimeout(() => inflightCancelRef.current.delete(route.id), 5000);
    try {
      await onCancelRoute({ sequence: route.sequence, routeId: route.routeId });
      // Cancel also produces a CXLPEND transition (<~500ms). Use the same optimistic
      // spinner + staged refresh so the final CANCEL status appears without manual refresh.
      markReplacing(route.id);
      if (onRefresh) await onRefresh();
    } finally {
      window.clearTimeout(safety);
      inflightCancelRef.current.delete(route.id);
    }
  };

  const renderRow = (route: Route) => {
    const effectiveRoute = replacingRouteIds.has(route.id) && !['CXLRPRQ', 'CXLREP'].includes(route.status)
      ? { ...route, status: 'CXLRPRQ' as const }
      : route;
    return (
      <tr key={route.id} className={`border-b border-border/50 hover:bg-muted/50 transition-colors text-xs h-8 ${selectedRouteIds.has(route.id) ? 'bg-primary/5' : ''}`}>
        {/* Selection checkbox */}
        <td className="px-2 text-center">
          <input
            type="checkbox"
            aria-label={`Select route ${route.sequence}.${route.routeId}`}
            checked={selectedRouteIds.has(route.id)}
            onChange={() => toggleRouteSelection(route.id)}
            onClick={(e) => e.stopPropagation()}
          />
        </td>
        {/* Actions */}
        <td className="px-2">
          <RouteActionMenu
            route={effectiveRoute}
            currentTrader={currentTrader}
            onCancel={(r) => { setSelectedRoute(r); setCancelDialogOpen(true); }}
            onModify={(r) => { setSelectedRoute(r); setModifyDialogOpen(true); }}
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
  };

  const renderSubGroupHeader = (primaryKey: string, subKey: string, subRoutes: Route[], isExpanded: boolean) => (
    <tr
      key={`${primaryKey}-${subKey}`}
      className="bg-secondary/20 border-y border-border/40 cursor-pointer select-none"
      onClick={() => toggleGroup(`${primaryKey}-${subKey}`)}
    >
      <td colSpan={TOTAL_COLS} className="px-8 py-1 text-xs">
        <div className="flex items-center gap-1.5">
          {isExpanded
            ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
            : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
          <span className="text-muted-foreground">{ROUTE_GROUP_BY_LABELS[groupConfig.secondary]}:</span>
          <span className="font-medium">{subKey}</span>
          <span className="text-muted-foreground/60">({subRoutes.length})</span>
        </div>
      </td>
    </tr>
  );

  // Check if any modification functionality is available
  const hasModifyCapability = !!onCancelRoute && !!onModifyRoute;

  return (
    <TooltipProvider>
      <div className="bg-card border border-border rounded-lg overflow-hidden flex flex-col h-full min-h-0">
        {/* Group-by bar with primary and secondary grouping */}
        <div className="border-b border-border px-4 py-1.5 bg-secondary/30 flex items-center gap-3 text-xs text-muted-foreground shrink-0">
          <Layers className="h-3.5 w-3.5" />
          <span>Group by</span>
          {/* Primary group */}
          <Select value={groupConfig.primary} onValueChange={(v) => handleGroupByChange('primary', v as RouteGroupByValue)}>
            <SelectTrigger className="h-6 text-xs w-28 border-0 bg-transparent focus:ring-0 p-0">
              <SelectValue placeholder="Primary..." />
            </SelectTrigger>
            <SelectContent>
              {ROUTE_GROUP_BY_OPTIONS.map(opt => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-muted-foreground/50">then</span>
          {/* Secondary group */}
          <Select value={groupConfig.secondary} onValueChange={(v) => handleGroupByChange('secondary', v as RouteGroupByValue)}>
            <SelectTrigger className="h-6 text-xs w-28 border-0 bg-transparent focus:ring-0 p-0">
              <SelectValue placeholder="Secondary..." />
            </SelectTrigger>
            <SelectContent>
              {ROUTE_GROUP_BY_OPTIONS.map(opt => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">{opt.label}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {hasActiveFilters && (
            <button
              onClick={() => { setStatusFilter([]); setBrokerFilter([]); setTraderFilter([]); setTickerFilter(''); }}
              className="ml-auto flex items-center gap-1 text-primary hover:underline"
            >
              <RotateCcw className="h-3 w-3" />Reset filters
            </button>
          )}
          <button
            onClick={() => setRateDiagnosticOpen(true)}
            className={`${hasActiveFilters ? '' : 'ml-auto'} flex items-center gap-1 text-xs px-2 py-0.5 border border-border rounded hover:bg-secondary transition-colors`}
            title="Diagnose routes with missing strategy Rate field"
          >
            Diagnose Rate
          </button>
        </div>

        {/* Batch action bar — visible only when at least one route is selected */}
        {selectedRouteIds.size > 0 && (
          <div className="flex items-center gap-3 px-3 py-1.5 bg-primary/5 border-t border-b border-primary/20 text-xs">
            <span className="font-semibold text-primary">
              {selectedRouteIds.size} route{selectedRouteIds.size === 1 ? '' : 's'} selected
            </span>
            {hasModifyCapability && (
              <>
                <button
                  onClick={() => setBatchModifyOpen(true)}
                  className="px-2 py-0.5 rounded border border-primary/40 bg-primary/10 hover:bg-primary/20 transition-colors"
                  title="Apply the same modification to all selected routes"
                >
                  Batch Modify…
                </button>
                <button
                  onClick={() => setBatchCancelOpen(true)}
                  className="px-2 py-0.5 rounded border border-destructive/40 bg-destructive/10 hover:bg-destructive/20 text-destructive transition-colors"
                  title="Cancel all selected routes"
                >
                  Batch Cancel…
                </button>
              </>
            )}
            <button onClick={clearSelection} className="ml-auto text-muted-foreground hover:text-foreground">
              Clear selection
            </button>
          </div>
        )}

        <ScrollArea className="flex-1 min-h-0">
          <div className="text-[10px] text-muted-foreground/60 px-3 py-0.5 italic" aria-hidden="true">
            ↔ scroll horizontally for more columns (Shift + mouse wheel)
          </div>
          <table className="trading-table min-w-max">
            <thead className="sticky top-0 z-10">
              <tr>
                {/* Select-all checkbox */}
                <th className="w-8 text-center">
                  <input
                    type="checkbox"
                    aria-label="Select all visible routes"
                    checked={filteredRoutes.length > 0 && filteredRoutes.every(r => selectedRouteIds.has(r.id))}
                    ref={(el) => {
                      if (el) {
                        const someSelected = filteredRoutes.some(r => selectedRouteIds.has(r.id));
                        const allSelected = filteredRoutes.length > 0 && filteredRoutes.every(r => selectedRouteIds.has(r.id));
                        el.indeterminate = someSelected && !allSelected;
                      }
                    }}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedRouteIds(new Set(filteredRoutes.map(r => r.id)));
                      } else {
                        clearSelection();
                      }
                    }}
                  />
                </th>
                {/* Actions */}
                <th className="w-10 text-center">Actions</th>
                {/* Order# */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('sequence')}>
                  <div className="flex items-center gap-1">Order#{getSortIcon('sequence')}</div>
                </th>
                {/* Route# */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('routeId')}>
                  <div className="flex items-center gap-1">Route#{getSortIcon('routeId')}</div>
                </th>
                {/* Ticker */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors">
                  <div className="flex items-center gap-1">
                    <span onClick={() => handleSort('ticker')}>Ticker{getSortIcon('ticker')}</span>
                    {textFilterPopover(tickerFilter, setTickerFilter, 'Filter ticker...')}
                  </div>
                </th>
                {/* Exchange */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('exchange')}>
                  <div className="flex items-center gap-1">Exchange{getSortIcon('exchange')}</div>
                </th>
                {/* Side */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('side')}>
                  <div className="flex items-center gap-1">Side{getSortIcon('side')}</div>
                </th>
                {/* Status */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors">
                  <div className="flex items-center gap-1">
                    <span onClick={() => handleSort('status')}>Status{getSortIcon('status')}</span>
                    {multiSelectFilterPopover('status', availableStatuses, statusFilter, setStatusFilter, statusFilterMode, setStatusFilterMode)}
                  </div>
                </th>
                {/* Type */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('orderType')}>
                  <div className="flex items-center gap-1">Type{getSortIcon('orderType')}</div>
                </th>
                {/* Qty */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('amount')}>
                  <div className="flex items-center justify-end gap-1">Qty{getSortIcon('amount')}</div>
                </th>
                {/* %Filled */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right">
                  <div className="flex items-center justify-end gap-1">%Filled</div>
                </th>
                {/* Filled */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('filled')}>
                  <div className="flex items-center justify-end gap-1">Filled{getSortIcon('filled')}</div>
                </th>
                {/* Working */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('working')}>
                  <div className="flex items-center justify-end gap-1">Working{getSortIcon('working')}</div>
                </th>
                {/* Avg Px */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('avgPrice')}>
                  <div className="flex items-center justify-end gap-1">Avg Px{getSortIcon('avgPrice')}</div>
                </th>
                {/* Limit Px */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('limitPrice')}>
                  <div className="flex items-center justify-end gap-1">Limit Px{getSortIcon('limitPrice')}</div>
                </th>
                {/* Last Px */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('lastPrice')}>
                  <div className="flex items-center justify-end gap-1">Last Px{getSortIcon('lastPrice')}</div>
                </th>
                {/* Last Shr */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('lastShares')}>
                  <div className="flex items-center justify-end gap-1">Last Shr{getSortIcon('lastShares')}</div>
                </th>
                {/* Broker */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors">
                  <div className="flex items-center gap-1">
                    <span onClick={() => handleSort('broker')}>Broker{getSortIcon('broker')}</span>
                    {multiSelectFilterPopover('broker', availableBrokers, brokerFilter, setBrokerFilter, brokerFilterMode, setBrokerFilterMode)}
                  </div>
                </th>
                {/* Trader */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors">
                  <div className="flex items-center gap-1">
                    <span onClick={() => handleSort('trader')}>Trader{getSortIcon('trader')}</span>
                    {multiSelectFilterPopover('trader', availableTraders, traderFilter, setTraderFilter, traderFilterMode, setTraderFilterMode)}
                  </div>
                </th>
                {/* Strategy */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('strategyType')}>
                  <div className="flex items-center gap-1">Strategy{getSortIcon('strategyType')}</div>
                </th>
                {/* Strat Params */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('strategyPartRate1')}>
                  <div className="flex items-center gap-1">Strat Params{getSortIcon('strategyPartRate1')}</div>
                </th>
                {/* Slice */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('sliceIndex')}>
                  <div className="flex items-center gap-1">Slice{getSortIcon('sliceIndex')}</div>
                </th>
                {/* Slice Status */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('sliceStatus')}>
                  <div className="flex items-center gap-1">Slice Status{getSortIcon('sliceStatus')}</div>
                </th>
                {/* Schedule */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('scheduledStart')}>
                  <div className="flex items-center gap-1">Schedule{getSortIcon('scheduledStart')}</div>
                </th>
                {/* Notes */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('notes')}>
                  <div className="flex items-center gap-1">Notes{getSortIcon('notes')}</div>
                </th>
                {/* Reason */}
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('reasonCode')}>
                  <div className="flex items-center gap-1">Reason{getSortIcon('reasonCode')}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              {isLoading && filteredRoutes.length === 0 ? (
                <tr>
                  <td colSpan={TOTAL_COLS} className="text-center py-12 text-muted-foreground">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="h-8 w-8 opacity-40" />
                      <span className="text-sm">Loading routes...</span>
                    </div>
                  </td>
                </tr>
              ) : filteredRoutes.length === 0 ? (
                <tr>
                  <td colSpan={TOTAL_COLS} className="text-center py-12 text-muted-foreground">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="h-8 w-8 opacity-40" />
                      <span className="text-sm">No routes found matching your criteria</span>
                    </div>
                  </td>
                </tr>
              ) : (
                groupedRoutes.map(group => (
                  <Fragment key={group.key}>
                    {/* Primary group header */}
                    {groupConfig.primary !== 'none' && (
                      <tr
                        className="bg-secondary/40 border-y border-border/60 cursor-pointer select-none"
                        onClick={() => toggleGroup(group.key)}
                      >
                        <td colSpan={TOTAL_COLS} className="px-4 py-1.5 text-xs font-semibold">
                          <div className="flex items-center gap-1.5">
                            {expandedGroups.has(group.key)
                              ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                              : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                            <span className="text-primary">{ROUTE_GROUP_BY_LABELS[groupConfig.primary]}:</span>{' '}
                            {group.key}
                            <span className="ml-2 text-muted-foreground/60">
                              ({group.subGroups 
                                ? group.subGroups.reduce((sum, sg) => sum + sg.routes.length, 0)
                                : group.routes.length
                              })
                            </span>
                          </div>
                        </td>
                      </tr>
                    )}
                    {/* Secondary groups or direct rows */}
                    {(groupConfig.primary === 'none' || expandedGroups.has(group.key)) && (
                      group.subGroups ? (
                        group.subGroups.map(subGroup => (
                          <Fragment key={`${group.key}-${subGroup.key}`}>
                            {renderSubGroupHeader(group.key, subGroup.key, subGroup.routes, expandedGroups.has(`${group.key}-${subGroup.key}`))}
                            {(expandedGroups.has(`${group.key}-${subGroup.key}`)) && subGroup.routes.map(renderRow)}
                          </Fragment>
                        ))
                      ) : (
                        group.routes.map(renderRow)
                      )
                    )}
                  </Fragment>
                ))
              )}
            </tbody>
          </table>
        </ScrollArea>

        {/* Table Footer */}
        <div className="border-t border-border px-4 py-2 bg-secondary/30 flex items-center justify-between text-xs text-muted-foreground shrink-0">
          <div className="flex items-center gap-3">
            <span>Showing {filteredRoutes.length} of {routes.length} route{filteredRoutes.length !== 1 ? 's' : ''}</span>
            {groupConfig.primary !== 'none' && (
              <span className="text-primary">{groupedRoutes.length} group{groupedRoutes.length !== 1 ? 's' : ''}</span>
            )}
            {statusFilter.length > 0 && (
              <span className={`text-xs ${statusFilterMode === 'exclude' ? 'text-destructive' : 'text-primary'}`}>
                Status {statusFilterMode === 'include' ? '⊃' : '⊄'} [{statusFilter.join(', ')}]
              </span>
            )}
            {brokerFilter.length > 0 && (
              <span className={`text-xs ${brokerFilterMode === 'exclude' ? 'text-destructive' : 'text-primary'}`}>
                Broker {brokerFilterMode === 'include' ? '⊃' : '⊄'} [{brokerFilter.join(', ')}]
              </span>
            )}
            {traderFilter.length > 0 && (
              <span className={`text-xs ${traderFilterMode === 'exclude' ? 'text-destructive' : 'text-primary'}`}>
                Trader {traderFilterMode === 'include' ? '⊃' : '⊄'} [{traderFilter.join(', ')}]
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Modification Dialogs */}
      {hasModifyCapability && (
        <>
          <CancelRouteDialog
            route={selectedRoute}
            open={cancelDialogOpen}
            onOpenChange={setCancelDialogOpen}
            onConfirm={handleCancel}
          />
          <UnifiedModifyRouteDialog
            route={selectedRoute}
            open={modifyDialogOpen}
            onOpenChange={setModifyDialogOpen}
            onSubmit={async (req) => {
              if (!onModifyRoute) return;
              await onModifyRoute(req);
              if (selectedRoute) markReplacing(selectedRoute.id);
              if (onRefresh) await onRefresh();
            }}
          />
        </>
      )}
      <RateDiagnosticDialog open={rateDiagnosticOpen} onOpenChange={setRateDiagnosticOpen} />

      {/* Batch operation dialogs */}
      {hasModifyCapability && (
        <>
          <BatchCancelDialog
            routes={filteredRoutes.filter(r => selectedRouteIds.has(r.id))}
            open={batchCancelOpen}
            onOpenChange={setBatchCancelOpen}
            onSubmit={async (req) => { if (onCancelRoute) await onCancelRoute(req); }}
            onEachSubmitted={(r) => markReplacing(r.id)}
            onComplete={async () => { clearSelection(); if (onRefresh) await onRefresh(); }}
          />
          <BatchModifyDialog
            routes={filteredRoutes.filter(r => selectedRouteIds.has(r.id))}
            open={batchModifyOpen}
            onOpenChange={setBatchModifyOpen}
            onEachSubmitted={(r) => markReplacing(r.id)}
            onComplete={async () => { clearSelection(); if (onRefresh) await onRefresh(); }}
          />
        </>
      )}
    </TooltipProvider>
  );
}
