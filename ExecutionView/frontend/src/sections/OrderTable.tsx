import { useState, useCallback, useMemo, useEffect, Fragment } from 'react';
import {
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
  AlertCircle,
  Layers,
  ChevronDown,
  ChevronRight,
  Filter,
  Search,
  X,
  Edit3,
  GitBranch,
} from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { formatNumber } from '@/lib/format-utils';
import { ORDER_GROUP_BY_OPTIONS, ORDER_GROUP_BY_LABELS, STATUS_OPTIONS, ORDER_TYPE_OPTIONS, type OrderGroupByValue } from '@/lib/table-constants';
import type { Order, OrderStatus, OrderSide, OrderFilters, ModifyOrderRequest, RouteOrderRequest } from '@/types';
import { OrderModifyDialog, type OrderUpdates } from '@/components/order-modify-dialog';
import { RouteOrderDialog, type RouteOrderData } from '@/components/order-route-dialog';
import { BatchRouteOrderDialog } from '@/components/batch-route-order-dialog';

type SortField = keyof Order | null;
type SortDirection = 'asc' | 'desc';

interface OrderTableProps {
  orders: Order[];
  allOrders: Order[];
  selectedOrders: Set<string>;
  onSelectionChange: (selectedIds: Set<string>) => void;
  isLoading: boolean;
  filters: OrderFilters;
  onFilterChange: (filters: OrderFilters) => void;
  onModifyOrder?: (request: ModifyOrderRequest) => Promise<void>;
  onRouteOrder?: (request: RouteOrderRequest) => Promise<void>;
  currentTrader?: string;
}

interface SortConfig {
  field: SortField;
  direction: SortDirection;
}

const TOTAL_COLS = 28; // 27 data columns + 1 actions column

export function OrderTable({ orders, allOrders, selectedOrders, onSelectionChange, isLoading, filters, onFilterChange, onModifyOrder, onRouteOrder, currentTrader }: OrderTableProps) {
  const [sortConfig, setSortConfig] = useState<SortConfig>({ field: 'createdAt', direction: 'desc' });
  const [groupBy, setGroupBy] = useState<OrderGroupByValue>('exchange');
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());
  const [modifyOrder, setModifyOrder] = useState<Order | null>(null);
  const [isModifyDialogOpen, setIsModifyDialogOpen] = useState(false);
  const [routeOrder, setRouteOrder] = useState<Order | null>(null);
  const [isRouteDialogOpen, setIsRouteDialogOpen] = useState(false);
  const [isBatchRouteDialogOpen, setIsBatchRouteDialogOpen] = useState(false);

  const toggleGroup = useCallback((key: string) => {
    setExpandedGroups(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  // Reset expanded groups when groupBy changes (all folded by default)
  const handleGroupByChange = useCallback((v: OrderGroupByValue) => {
    setGroupBy(v);
    setExpandedGroups(new Set());
  }, []);

  const handleSort = useCallback((field: keyof Order) => {
    setSortConfig(prev => ({
      field,
      direction: prev.field === field && prev.direction === 'asc' ? 'desc' : 'asc',
    }));
  }, []);

  const sortedOrders = useMemo(() => {
    if (!sortConfig.field) return orders;
    return [...orders].sort((a, b) => {
      const aValue = a[sortConfig.field!];
      const bValue = b[sortConfig.field!];
      const aNull = aValue === undefined || aValue === null;
      const bNull = bValue === undefined || bValue === null;
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
  }, [orders, sortConfig]);

  const groupedOrders = useMemo(() => {
    if (groupBy === 'none') return [{ key: '_all', orders: sortedOrders }];
    const groups: Record<string, Order[]> = {};
    for (const order of sortedOrders) {
      const raw = order[groupBy as keyof Order];
      const key = raw != null && raw !== '' ? String(raw) : '(empty)';
      if (!groups[key]) groups[key] = [];
      groups[key].push(order);
    }
    return Object.entries(groups)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, orders]) => ({ key, orders }));
  }, [sortedOrders, groupBy]);

  const allSelected = orders.length > 0 && orders.every(order => selectedOrders.has(order.id));
  const someSelected = orders.some(order => selectedOrders.has(order.id)) && !allSelected;

  const toggleSelectAll = useCallback(() => {
    if (allSelected) {
      const newSelected = new Set(selectedOrders);
      orders.forEach(order => newSelected.delete(order.id));
      onSelectionChange(newSelected);
    } else {
      const newSelected = new Set(selectedOrders);
      orders.forEach(order => newSelected.add(order.id));
      onSelectionChange(newSelected);
    }
  }, [allSelected, orders, selectedOrders, onSelectionChange]);

  const toggleSelectOrder = useCallback((orderId: string) => {
    const newSelected = new Set(selectedOrders);
    if (newSelected.has(orderId)) {
      newSelected.delete(orderId);
    } else {
      newSelected.add(orderId);
    }
    onSelectionChange(newSelected);
  }, [selectedOrders, onSelectionChange]);

  const toggleSelectGroup = useCallback((groupOrders: Order[]) => {
    const ids = groupOrders.map(o => o.id);
    const allInGroupSelected = ids.length > 0 && ids.every(id => selectedOrders.has(id));
    const next = new Set(selectedOrders);
    if (allInGroupSelected) {
      ids.forEach(id => next.delete(id));
    } else {
      ids.forEach(id => next.add(id));
    }
    onSelectionChange(next);
  }, [selectedOrders, onSelectionChange]);

  const getSortIcon = (field: keyof Order) => {
    if (sortConfig.field !== field) {
      return <ArrowUpDown className="h-3.5 w-3.5 text-muted-foreground/50" />;
    }
    return sortConfig.direction === 'asc'
      ? <ArrowUp className="h-3.5 w-3.5 text-primary" />
      : <ArrowDown className="h-3.5 w-3.5 text-primary" />;
  };

  const getStatusBadge = (status: OrderStatus) => {
    const map: Record<OrderStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }> = {
      NEW:            { variant: 'outline' },
      ASSIGN:         { variant: 'outline', className: 'border-cyan-500 text-cyan-600' },
      WORKING:        { variant: 'default', className: 'bg-blue-500/90 hover:bg-blue-600' },
      PARTIAL:        { variant: 'default', className: 'bg-amber-500/90 hover:bg-amber-600' },
      FILLED:         { variant: 'default', className: 'bg-emerald-500/90 hover:bg-emerald-600' },
      CANCELLED:      { variant: 'secondary' },
      COMPLETED:      { variant: 'default', className: 'bg-green-600/90 hover:bg-green-700' },
      QUEUED:         { variant: 'default', className: 'bg-purple-500/90 hover:bg-purple-600' },
      SUSPENDED:      { variant: 'default', className: 'bg-orange-500/90 hover:bg-orange-600' },
      PENDING_CANCEL: { variant: 'destructive', className: 'bg-red-400/90' },
      REJECTED:       { variant: 'destructive' },
      SENT:           { variant: 'default', className: 'bg-sky-500/90 hover:bg-sky-600' },
    };
    const s = map[status] ?? { variant: 'outline' as const };
    return <Badge variant={s.variant} className={`text-[10px] px-1.5 py-0 leading-4 ${s.className ?? ''}`}>{status}</Badge>;
  };

  const getSideClass = (side: OrderSide) => side === 'BUY' ? 'side-buy' : 'side-sell';

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPercentFilled = (order: Order) => {
    if (order.quantity <= 0) return '';
    return order.percentFilled.toFixed(0) + '%';
  };

  // Check if order can be modified (per EMSX API spec)
  const canModifyOrder = (order: Order): boolean => {
    // Only orders with status NEW, ASSIGN, WORKING can be modified
    const eligibleStatuses: OrderStatus[] = ['NEW', 'ASSIGN', 'WORKING'];
    if (!eligibleStatuses.includes(order.status)) return false;
    
    // For WORKING orders, must have remaining quantity
    if (order.status === 'WORKING' && order.remainingQuantity <= 0) return false;
    
    return true;
  };

  const handleModifyClick = (order: Order) => {
    setModifyOrder(order);
    setIsModifyDialogOpen(true);
  };

  const handleModifyConfirm = async (order: Order, updates: OrderUpdates) => {
    if (!onModifyOrder) return;
    
    const request: ModifyOrderRequest = {
      orderId: order.id,
      orderType: updates.orderType,
      price: updates.price,
      quantity: updates.quantity,
      timeInForce: updates.timeInForce,
      stopPrice: updates.stopPrice,
    };
    
    await onModifyOrder(request);
    setIsModifyDialogOpen(false);
    setModifyOrder(null);
  };

  // Check if order can be routed (per EMSX API spec)
  const canRouteOrder = (order: Order): boolean => {
    // Only orders with status NEW, ASSIGN, WORKING, or PARTIAL can be routed
    const eligibleStatuses: OrderStatus[] = ['NEW', 'ASSIGN', 'WORKING', 'PARTIAL', 'SENT', 'QUEUED'];
    if (!eligibleStatuses.includes(order.status)) return false;
    
    // Must have remaining quantity to route
    if (order.remainingQuantity <= 0) return false;

    // Trader validation: current trader must match order's assigned trader
    if (currentTrader && order.trader && currentTrader.toUpperCase() !== order.trader.toUpperCase()) return false;
    
    return true;
  };

  const handleRouteClick = (order: Order) => {
    setRouteOrder(order);
    setIsRouteDialogOpen(true);
  };

  const handleRouteConfirm = async (order: Order, routeData: RouteOrderData) => {
    if (!onRouteOrder) return;

    const request: RouteOrderRequest = {
      orderId: order.id,
      broker: routeData.broker,
      strategy: routeData.strategy || undefined,
      quantity: routeData.quantity,
      orderType: routeData.orderType,
      price: routeData.price,
      stopPrice: routeData.stopPrice,
      timeInForce: routeData.timeInForce,
      exchangeDestination: routeData.exchangeDestination,
      notes: routeData.notes,
      strategyParams: routeData.strategyParams ?? undefined,
    };
    
    await onRouteOrder(request);
    setIsRouteDialogOpen(false);
    setRouteOrder(null);
  };

  const getPmNote = (order: Order) => {
    const parts: string[] = [];
    if (order.notes) parts.push(order.notes);
    if (parts.length > 0) return parts.join('');
    return order.execInstruction || order.customNote1 || order.customNote2
      || order.customNote3 || order.customNote4 || order.customNote5 || '';
  };

  const getStrategyDetail = (order: Order) => {
    if (!order.strategyType) return '';
    const parts: string[] = [];
    if (order.strategyPartRate != null) parts.push(`Rate: ${order.strategyPartRate.toFixed(0)}%`);
    if (order.strategyStyle) parts.push(`Style: ${order.strategyStyle}`);
    if (order.strategyStartTime) parts.push(`Start: ${order.strategyStartTime}`);
    if (order.strategyEndTime) parts.push(`End: ${order.strategyEndTime}`);
    return parts.join(' | ');
  };

  // ─── Filter helpers ─────────────────────────────────────────────────────────

  const traderOptions = useMemo(() => {
    const set = new Set<string>();
    for (const o of allOrders) {
      if (o.trader) set.add(o.trader);
    }
    return Array.from(set).sort().map(t => ({ value: t, label: t }));
  }, [allOrders]);

  const updateFilter = useCallback(<K extends keyof OrderFilters>(key: K, value: OrderFilters[K]) => {
    onFilterChange({ ...filters, [key]: value });
  }, [filters, onFilterChange]);

  const updateMultiFilter = useCallback((key: 'statusMulti' | 'orderTypeMulti' | 'traderMulti', value: string[]) => {
    onFilterChange({ ...filters, [key]: value });
  }, [filters, onFilterChange]);

  const updateSideFilter = useCallback((value: OrderSide | '') => {
    onFilterChange({ ...filters, side: value });
  }, [filters, onFilterChange]);


  const hasActiveFilters = useMemo(() => {
    return Object.entries(filters).some(([, v]) => {
      if (Array.isArray(v)) return v.length > 0;
      return v !== '' && v !== undefined && v !== null;
    });
  }, [filters]);

  const activeFilterCount = useMemo(() => {
    return Object.entries(filters).filter(([, v]) => {
      if (Array.isArray(v)) return v.length > 0;
      return v !== '' && v !== undefined && v !== null;
    }).length;
  }, [filters]);

  // Debug: Log order counts
  useEffect(() => {
    console.log(`[OrderTable] allOrders: ${allOrders.length}, orders: ${orders.length}, activeFilters: ${activeFilterCount}`);
  }, [allOrders.length, orders.length, activeFilterCount]);

  const textFilterPopover = (key: 'symbol' | 'portfolio' | 'exchange' | 'currency', placeholder: string) => {
    const active = !!(filters[key]);
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button
            onClick={e => e.stopPropagation()}
            className={`ml-auto p-0.5 rounded hover:bg-accent/80 ${active ? 'text-primary' : 'text-muted-foreground/30 hover:text-muted-foreground'}`}
          >
            <Filter className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-44 p-2" align="start" side="bottom">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
            <Input
              value={(filters[key] as string) || ''}
              onChange={e => updateFilter(key, e.target.value.toUpperCase())}
              placeholder={placeholder}
              className="pl-7 h-7 text-xs"
              autoFocus
            />
          </div>
          {active && (
            <button
              onClick={() => updateFilter(key, '')}
              className="mt-1.5 text-[10px] text-muted-foreground hover:text-primary"
            >
              Clear
            </button>
          )}
        </PopoverContent>
      </Popover>
    );
  };

  const multiFilterPopover = (
    key: 'statusMulti' | 'orderTypeMulti' | 'traderMulti',
    options: { value: string; label: string }[],
  ) => {
    const selected = (filters[key] ?? []) as string[];
    const active = selected.length > 0;
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button
            onClick={e => e.stopPropagation()}
            className={`ml-auto p-0.5 rounded hover:bg-accent/80 ${active ? 'text-primary' : 'text-muted-foreground/30 hover:text-muted-foreground'}`}
          >
            <Filter className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-44 p-1" align="start" side="bottom">
          <div
            className="flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-accent rounded"
            onMouseDown={e => { e.preventDefault(); updateMultiFilter(key, []); }}
          >
            <Checkbox checked={selected.length === 0} tabIndex={-1} className="pointer-events-none h-3.5 w-3.5" />
            <span className="text-xs font-medium text-muted-foreground">All</span>
          </div>
          <div className="border-t my-0.5" />
          <div className="max-h-48 overflow-y-auto">
            {options.map(opt => (
              <div
                key={opt.value}
                className="flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-accent rounded"
                onMouseDown={e => {
                  e.preventDefault();
                  const next = selected.includes(opt.value)
                    ? selected.filter(v => v !== opt.value)
                    : [...selected, opt.value];
                  updateMultiFilter(key, next);
                }}
              >
                <Checkbox checked={selected.includes(opt.value)} tabIndex={-1} className="pointer-events-none h-3.5 w-3.5" />
                <span className="text-xs">{opt.label}</span>
              </div>
            ))}
          </div>
        </PopoverContent>
      </Popover>
    );
  };

  const sideFilterPopover = () => {
    const active = !!filters.side;
    return (
      <Popover>
        <PopoverTrigger asChild>
          <button
            onClick={e => e.stopPropagation()}
            className={`ml-auto p-0.5 rounded hover:bg-accent/80 ${active ? 'text-primary' : 'text-muted-foreground/30 hover:text-muted-foreground'}`}
          >
            <Filter className="h-3 w-3" />
          </button>
        </PopoverTrigger>
        <PopoverContent className="w-28 p-1" align="start" side="bottom">
          {([['', 'All'], ['BUY', 'Buy'], ['SELL', 'Sell']] as const).map(([v, label]) => (
            <div
              key={v || 'all'}
              className={`px-2 py-1 text-xs cursor-pointer rounded hover:bg-accent ${(filters.side || '') === v ? 'font-semibold text-primary' : ''}`}
              onMouseDown={e => { e.preventDefault(); updateSideFilter(v); }}
            >
              {label}
            </div>
          ))}
        </PopoverContent>
      </Popover>
    );
  };

  // ─── Render ─────────────────────────────────────────────────────────────────

  if (isLoading && orders.length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground">
        <div className="flex flex-col items-center gap-3">
          <div className="spinner h-8 w-8" />
          <span className="text-sm">Loading orders...</span>
        </div>
      </div>
    );
  }

  return (
    <TooltipProvider>
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {/* Group-by bar — top of table */}
        <div className="border-b border-border px-4 py-1.5 bg-secondary/30 flex items-center gap-2 text-xs text-muted-foreground">
          <Layers className="h-3.5 w-3.5" />
          <span>Group by</span>
          <Select value={groupBy} onValueChange={(v) => handleGroupByChange(v as OrderGroupByValue)}>
            <SelectTrigger className="h-6 text-xs w-36 border-0 bg-transparent focus:ring-0 p-0">
              <SelectValue placeholder="Group by..." />
            </SelectTrigger>
            <SelectContent>
              {ORDER_GROUP_BY_OPTIONS.map(opt => (
                <SelectItem key={opt.value} value={opt.value} className="text-xs">
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {/* Order count indicator */}
          <span className="ml-4 text-xs">
            Showing <span className="font-semibold text-foreground">{orders.length}</span>
            {allOrders.length !== orders.length && (
              <span> of <span className="font-semibold text-foreground">{allOrders.length}</span></span>
            )} orders
            {activeFilterCount > 0 && (
              <span className="text-primary ml-1">({activeFilterCount} filter{activeFilterCount > 1 ? 's' : ''} active)</span>
            )}
          </span>
          {hasActiveFilters && (
            <button
              onClick={() => onFilterChange({})}
              className="ml-auto flex items-center gap-1 text-primary hover:underline"
            >
              <X className="h-3 w-3" />Clear filters
            </button>
          )}
          {selectedOrders.size > 0 && onRouteOrder && (
            <button
              onClick={() => setIsBatchRouteDialogOpen(true)}
              className={`${hasActiveFilters ? '' : 'ml-auto'} flex items-center gap-1 px-2 py-1 rounded bg-primary text-primary-foreground hover:bg-primary/90 text-xs font-medium`}
            >
              <GitBranch className="h-3 w-3" />Batch Route ({selectedOrders.size})
            </button>
          )}
        </div>

        <ScrollArea className="h-[calc(100vh-370px)]">
          <table className="trading-table min-w-max">
            <thead className="sticky top-0 z-10">
              <tr>
                <th className="w-10 text-center">
                  <Checkbox checked={allSelected} onCheckedChange={toggleSelectAll} aria-label="Select all orders" className={someSelected ? 'indeterminate' : ''} />
                </th>
                <th className="text-center w-10">Actions</th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('id')}>
                  <div className="flex items-center gap-1">Order ID{getSortIcon('id')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('symbol')}>
                  <div className="flex items-center gap-1">Ticker{getSortIcon('symbol')}{textFilterPopover('symbol', 'Filter ticker...')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('side')}>
                  <div className="flex items-center gap-1">Side{getSortIcon('side')}{sideFilterPopover()}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('status')}>
                  <div className="flex items-center gap-1">Status{getSortIcon('status')}{multiFilterPopover('statusMulti', STATUS_OPTIONS)}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('orderType')}>
                  <div className="flex items-center gap-1">Type{getSortIcon('orderType')}{multiFilterPopover('orderTypeMulti', ORDER_TYPE_OPTIONS)}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('quantity')}>
                  <div className="flex items-center justify-end gap-1">Qty{getSortIcon('quantity')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('percentFilled')}>
                  <div className="flex items-center justify-end gap-1">%Filled{getSortIcon('percentFilled')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('price')}>
                  <div className="flex items-center justify-end gap-1">Limit Px{getSortIcon('price')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('avgPrice')}>
                  <div className="flex items-center justify-end gap-1">Avg Px{getSortIcon('avgPrice')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('arrivalPrice')}>
                  <div className="flex items-center justify-end gap-1">Arr Px{getSortIcon('arrivalPrice')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('lastPrice')}>
                  <div className="flex items-center justify-end gap-1">Last Px{getSortIcon('lastPrice')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('mktVwap')}>
                  <div className="flex items-center justify-end gap-1">Ivl VWAP{getSortIcon('mktVwap')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('dollarValueUsd')}>
                  <div className="flex items-center justify-end gap-1">$Value{getSortIcon('dollarValueUsd')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('pctChange')}>
                  <div className="flex items-center justify-end gap-1">%Change{getSortIcon('pctChange')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('adv5d')}>
                  <div className="flex items-center justify-end gap-1">ADV 5D{getSortIcon('adv5d')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('portfolio')}>
                  <div className="flex items-center gap-1">Portfolio{getSortIcon('portfolio')}{textFilterPopover('portfolio', 'Filter...')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('trader')}>
                  <div className="flex items-center gap-1">Trader{getSortIcon('trader')}{multiFilterPopover('traderMulti', traderOptions)}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('exchange')}>
                  <div className="flex items-center gap-1">Exchange{getSortIcon('exchange')}{textFilterPopover('exchange', 'Filter...')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('currency')}>
                  <div className="flex items-center gap-1">Currency{getSortIcon('currency')}{textFilterPopover('currency', 'Filter...')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors text-right" onClick={() => handleSort('fxRate')}>
                  <div className="flex items-center justify-end gap-1">FX Rate{getSortIcon('fxRate')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('strategyType')}>
                  <div className="flex items-center gap-1">Strategy{getSortIcon('strategyType')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('strategyPartRate')}>
                  <div className="flex items-center gap-1">Strat Params{getSortIcon('strategyPartRate')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('scheduleType')}>
                  <div className="flex items-center gap-1">Schedule{getSortIcon('scheduleType')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('childRouteCount')}>
                  <div className="flex items-center gap-1">Children{getSortIcon('childRouteCount')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('notes')}>
                  <div className="flex items-center gap-1">PM Note{getSortIcon('notes')}</div>
                </th>
                <th className="cursor-pointer hover:bg-secondary/70 transition-colors" onClick={() => handleSort('createdAt')}>
                  <div className="flex items-center gap-1">Created{getSortIcon('createdAt')}</div>
                </th>
              </tr>
            </thead>
            <tbody>
              {orders.length === 0 && (
                <tr>
                  <td colSpan={TOTAL_COLS} className="text-center py-12 text-muted-foreground">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="h-8 w-8 opacity-40" />
                      <span className="text-sm">No orders found matching your criteria</span>
                    </div>
                  </td>
                </tr>
              )}
              {groupedOrders.map(group => {
                // Capture this group's order list in a stable local so the
                // checkbox handler cannot accidentally pick up a sibling
                // group's array reference (avoids any potential stale-closure
                // selection bleed across groups).
                const groupOrdersSnapshot = group.orders;
                const groupAllSelected =
                  groupOrdersSnapshot.length > 0 &&
                  groupOrdersSnapshot.every(o => selectedOrders.has(o.id));
                return (
                <Fragment key={group.key}>
                  {groupBy !== 'none' && (
                    <tr
                      className="bg-secondary/40 border-y border-border/60 cursor-pointer select-none"
                      onClick={() => toggleGroup(group.key)}
                    >
                      <td colSpan={TOTAL_COLS} className="px-4 py-1.5 text-xs font-semibold">
                        <div className="flex items-center gap-1.5">
                          <span
                            className="flex items-center"
                            title="Select all orders in this group"
                            onClick={(e) => e.stopPropagation()}
                            onPointerDown={(e) => e.stopPropagation()}
                          >
                            <Checkbox
                              checked={groupAllSelected}
                              onCheckedChange={() => toggleSelectGroup(groupOrdersSnapshot)}
                              aria-label={`Select all orders in group ${group.key}`}
                            />
                          </span>
                          {expandedGroups.has(group.key)
                            ? <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                            : <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />}
                          <span className="text-primary">{ORDER_GROUP_BY_LABELS[groupBy]}:</span>{' '}
                          {group.key}
                          <span className="ml-2 text-muted-foreground/60">({group.orders.length})</span>
                        </div>
                      </td>
                    </tr>
                  )}
                  {(groupBy === 'none' || expandedGroups.has(group.key)) && group.orders.map((order) => (
                    <tr key={order.id} className={selectedOrders.has(order.id) ? 'selected' : ''}>
                      <td className="text-center">
                        <Checkbox checked={selectedOrders.has(order.id)} onCheckedChange={() => toggleSelectOrder(order.id)} aria-label={`Select order ${order.id}`} />
                      </td>
                  <td className="text-center">
                    <div className="flex items-center justify-center gap-1">
                      {canModifyOrder(order) && onModifyOrder && (
                        <button
                          onClick={() => handleModifyClick(order)}
                          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-primary transition-colors"
                          title="Modify order"
                        >
                          <Edit3 className="h-3.5 w-3.5" />
                        </button>
                      )}
                      {canRouteOrder(order) && onRouteOrder && (
                        <button
                          onClick={() => handleRouteClick(order)}
                          className="p-1 rounded hover:bg-accent text-muted-foreground hover:text-blue-500 transition-colors"
                          title="Route order to broker"
                        >
                          <GitBranch className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </div>
                  </td>
                      <td className="font-mono text-xs">{order.id}</td>
                      <td className="font-semibold">{order.symbol}</td>
                      <td className={getSideClass(order.side)}>{order.side}</td>
                      <td>{getStatusBadge(order.status)}</td>
                      <td className="text-muted-foreground">{order.orderType}</td>
                      <td className={`text-right font-mono-numbers ${order.side === 'BUY' ? 'text-green-500' : 'text-red-500'}`}>
                        <Tooltip>
                          <TooltipTrigger asChild>
                            <span className="cursor-help">{order.quantity.toLocaleString()}</span>
                          </TooltipTrigger>
                          <TooltipContent>
                            <div className="text-xs space-y-1">
                              <div>Total: {order.quantity.toLocaleString()}</div>
                              <div className="text-green-400">Filled: {order.filledQuantity.toLocaleString()}</div>
                              <div className="text-yellow-400">Remaining: {order.remainingQuantity.toLocaleString()}</div>
                            </div>
                          </TooltipContent>
                        </Tooltip>
                      </td>
                      <td className="text-right font-mono-numbers text-xs">{getPercentFilled(order)}</td>
                      <td className="text-right font-mono-numbers">{order.price != null ? formatNumber(order.price) : ''}</td>
                      <td className="text-right font-mono-numbers text-xs">{order.avgPrice != null ? formatNumber(order.avgPrice) : ''}</td>
                      <td className="text-right font-mono-numbers text-xs text-muted-foreground">{order.arrivalPrice != null ? formatNumber(order.arrivalPrice) : ''}</td>
                      <td className="text-right font-mono-numbers text-xs text-muted-foreground">{order.lastPrice != null ? formatNumber(order.lastPrice) : ''}</td>
                      <td className="text-right font-mono-numbers text-xs text-muted-foreground">{order.mktVwap != null ? formatNumber(order.mktVwap) : ''}</td>
                      <td className="text-right font-mono-numbers text-xs">{order.dollarValueUsd != null ? '$' + order.dollarValueUsd.toLocaleString('en-US', { maximumFractionDigits: 0 }) : ''}</td>
                      <td className={`text-right font-mono-numbers text-xs ${order.pctChange != null ? (order.pctChange > 0 ? 'text-green-500' : order.pctChange < 0 ? 'text-red-500' : '') : ''}`}>
                        {order.pctChange != null ? (order.pctChange > 0 ? '+' : '') + order.pctChange.toFixed(2) + '%' : ''}
                      </td>
                      <td className="text-right font-mono-numbers text-xs text-muted-foreground">{order.adv5d != null ? order.adv5d.toLocaleString() : ''}</td>
                      <td className="font-mono text-xs">{order.portfolio}</td>
                      <td className="text-xs">{order.trader}</td>
                      <td className="text-xs">{order.exchange || ''}</td>
                      <td className="text-xs">{order.currency || ''}</td>
                      <td className="text-right font-mono-numbers text-xs text-muted-foreground">{order.fxRate != null ? order.fxRate.toFixed(4) : ''}</td>
                      <td className="text-xs font-medium">{order.strategyType || ''}</td>
                      <td className="text-xs text-muted-foreground truncate max-w-[120px]" title={getStrategyDetail(order)}>{getStrategyDetail(order)}</td>
                      <td className="text-xs">{order.scheduleType || ''}{order.scheduleStatus ? ` (${order.scheduleStatus})` : ''}</td>
                      <td className="text-center text-xs font-mono-numbers">{order.childRouteCount != null ? order.childRouteCount : ''}</td>
                      <td className="text-xs truncate max-w-[180px]" title={getPmNote(order)}>{getPmNote(order)}</td>
                  <td className="text-muted-foreground text-xs">{formatDate(order.createdAt)}</td>
                </tr>
              ))}
            </Fragment>
          );
          })}
        </tbody>
          </table>
        </ScrollArea>

        {/* Table Footer */}
        <div className="border-t border-border px-4 py-2 bg-secondary/30 flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-3">
            <span>Showing {orders.length}{allOrders.length !== orders.length ? ` of ${allOrders.length}` : ''} order{orders.length !== 1 ? 's' : ''}</span>
            {groupBy !== 'none' && (
              <span className="text-primary">{groupedOrders.length} group{groupedOrders.length !== 1 ? 's' : ''}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {selectedOrders.size > 0 && (
              <span className="text-primary">{selectedOrders.size} selected</span>
            )}
          </div>
        </div>
      </div>

      <OrderModifyDialog
        order={modifyOrder}
        open={isModifyDialogOpen}
        onOpenChange={setIsModifyDialogOpen}
        onConfirm={handleModifyConfirm}
      />

      <RouteOrderDialog
        order={routeOrder}
        open={isRouteDialogOpen}
        onOpenChange={setIsRouteDialogOpen}
        onConfirm={handleRouteConfirm}
      />

      <BatchRouteOrderDialog
        orders={orders.filter(o => selectedOrders.has(o.id))}
        open={isBatchRouteDialogOpen}
        onOpenChange={setIsBatchRouteDialogOpen}
        onComplete={() => onSelectionChange(new Set())}
      />
    </TooltipProvider>
  );
}
