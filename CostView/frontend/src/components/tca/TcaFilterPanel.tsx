/**
 * TcaFilterPanel — filter form for TCA analysis.
 *
 * Renders inputs for: Order IDs, Algo, Date Range, Broker, Symbol.
 * Calls onSearch when the user submits.
 */

import { useState } from 'react';
import type { TcaFilterPayload } from '@/services/tca-api';

interface TcaFilterPanelProps {
  onSearch: (filters: TcaFilterPayload, limit: number) => void;
  isLoading: boolean;
}

export function TcaFilterPanel({ onSearch, isLoading }: TcaFilterPanelProps) {
  const [orderIds, setOrderIds] = useState('');
  const [algo, setAlgo] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [broker, setBroker] = useState('');
  const [symbol, setSymbol] = useState('');
  const [limit, setLimit] = useState(50);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();

    const filters: TcaFilterPayload = {};
    if (orderIds.trim()) {
      filters.order_ids = orderIds
        .split(/[\n,]+/)
        .map((s) => s.trim())
        .filter(Boolean);
    }
    if (algo) filters.algo = algo;
    // Convert yyyy-mm-dd → yyyymmdd for the API
    if (startDate) filters.start_date = startDate.replace(/-/g, '');
    if (endDate) filters.end_date = endDate.replace(/-/g, '');
    if (broker) filters.broker = broker;
    if (symbol) filters.symbol = symbol;

    onSearch(filters, limit);
  }

  function handleClear() {
    setOrderIds('');
    setAlgo('');
    setStartDate('');
    setEndDate('');
    setBroker('');
    setSymbol('');
    setLimit(50);
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-card border border-border rounded-lg p-4 space-y-4"
    >
      <h2 className="text-sm font-semibold text-foreground">TCA Filters</h2>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {/* Order IDs */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium" htmlFor="tca-order-ids">
            Order IDs (comma or newline separated)
          </label>
          <textarea
            id="tca-order-ids"
            className="rounded border border-input bg-background px-2 py-1.5 text-sm resize-none h-16 focus:outline-none focus:ring-1 focus:ring-primary"
            value={orderIds}
            onChange={(e) => setOrderIds(e.target.value)}
            placeholder="e.g. 12345, 67890"
          />
        </div>

        {/* Date range */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium">Date Range</label>
          <div className="flex gap-2 items-center">
            <input
              type="date"
              aria-label="Start date"
              className="flex-1 rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              value={startDate}
              onChange={(e) => setStartDate(e.target.value)}
            />
            <span className="text-muted-foreground text-xs">to</span>
            <input
              type="date"
              aria-label="End date"
              className="flex-1 rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
              value={endDate}
              onChange={(e) => setEndDate(e.target.value)}
            />
          </div>
        </div>

        {/* Algo */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium" htmlFor="tca-algo">
            Algorithm
          </label>
          <select
            id="tca-algo"
            className="rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            value={algo}
            onChange={(e) => setAlgo(e.target.value)}
          >
            <option value="">All</option>
            <option value="VWAP">VWAP</option>
            <option value="TWAP">TWAP</option>
            <option value="POV">POV</option>
            <option value="IS">IS</option>
            <option value="CLOSE">CLOSE</option>
          </select>
        </div>

        {/* Broker */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium" htmlFor="tca-broker">
            Broker
          </label>
          <input
            id="tca-broker"
            type="text"
            className="rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            value={broker}
            onChange={(e) => setBroker(e.target.value)}
            placeholder="e.g. CITI"
          />
        </div>

        {/* Symbol */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium" htmlFor="tca-symbol">
            Symbol (Bloomberg ticker)
          </label>
          <input
            id="tca-symbol"
            type="text"
            className="rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            placeholder="e.g. AAPL US Equity"
          />
        </div>

        {/* Result limit */}
        <div className="flex flex-col gap-1">
          <label className="text-xs text-muted-foreground font-medium" htmlFor="tca-limit">
            Max Orders
          </label>
          <select
            id="tca-limit"
            className="rounded border border-input bg-background px-2 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-primary"
            value={limit}
            onChange={(e) => setLimit(Number(e.target.value))}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
            <option value={200}>200</option>
          </select>
        </div>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-1">
        <button
          type="submit"
          disabled={isLoading}
          className="px-4 py-1.5 rounded bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
        >
          {isLoading ? 'Analyzing…' : 'Analyze'}
        </button>
        <button
          type="button"
          onClick={handleClear}
          className="px-4 py-1.5 rounded border border-border text-sm font-medium hover:bg-muted transition-colors"
        >
          Clear
        </button>
      </div>
    </form>
  );
}
