import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { CostViewFilterFormState } from '../types';

interface TcaFilterWorkbenchProps {
  form: CostViewFilterFormState;
  isLoading: boolean;
  onChange: (next: CostViewFilterFormState) => void;
  onReset: () => void;
  onSearch: () => void;
}

export function TcaFilterWorkbench({ form, isLoading, onChange, onReset, onSearch }: TcaFilterWorkbenchProps) {
  const [showAdvanced, setShowAdvanced] = useState(false);

  function update<K extends keyof CostViewFilterFormState>(key: K, value: CostViewFilterFormState[K]) {
    onChange({ ...form, [key]: value });
  }

  return (
    <Card className="gap-4">
      <CardHeader className="pb-0">
        <div className="flex items-center justify-between gap-4">
          <div>
            <CardTitle className="text-base">Analysis Filters</CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Run server-side TCA queries and keep the last-used filters locally.</p>
          </div>
          <Button type="button" variant="outline" size="sm" onClick={() => setShowAdvanced((current) => !current)}>
            {showAdvanced ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />} Advanced
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Order IDs</span>
            <textarea
              className="min-h-[96px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
              placeholder="12345, 67890"
              value={form.orderIds}
              onChange={(event) => update('orderIds', event.target.value)}
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Date Range</span>
            <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <input type="date" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.startDate} onChange={(event) => update('startDate', event.target.value)} />
              <span className="text-xs text-muted-foreground">to</span>
              <input type="date" className="rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.endDate} onChange={(event) => update('endDate', event.target.value)} />
            </div>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Algorithm</span>
            <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.algo} onChange={(event) => update('algo', event.target.value)}>
              <option value="">All</option>
              <option value="VWAP">VWAP</option>
              <option value="TWAP">TWAP</option>
              <option value="POV">POV</option>
              <option value="IS">IS</option>
              <option value="CLOSE">CLOSE</option>
            </select>
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Broker</span>
            <input type="text" className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="CITI" value={form.broker} onChange={(event) => update('broker', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Symbol</span>
            <input type="text" className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder="AAPL US Equity" value={form.symbol} onChange={(event) => update('symbol', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Max Orders</span>
            <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={form.limit} onChange={(event) => update('limit', Number(event.target.value))}>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
              <option value={200}>200</option>
            </select>
          </label>
        </div>

        {showAdvanced ? (
          <div className="rounded-lg border border-dashed border-border p-4">
            <label className="flex items-center gap-3 text-sm">
              <input type="checkbox" checked={form.warningOnly} onChange={(event) => update('warningOnly', event.target.checked)} />
              <span>Show only warning/critical orders from the currently fetched result set</span>
            </label>
            <p className="mt-2 text-xs text-muted-foreground">This filter is applied client-side after the server query returns.</p>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" onClick={onSearch} disabled={isLoading}>{isLoading ? 'Analyzing…' : 'Analyze'}</Button>
          <Button type="button" variant="outline" onClick={onReset}>Clear</Button>
        </div>
      </CardContent>
    </Card>
  );
}