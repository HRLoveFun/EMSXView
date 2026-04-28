/**
 * Market Broker Mapping — Settings section.
 *
 * Layout
 *   Rows : markets discovered from REAL orders/routes (route/order exchange
 *          code, with EUR-currency exchanges collapsing into the single key
 *          "EUR"). Once discovered, markets are persisted on the backend so
 *          they keep showing even when no live data is loaded.
 *   Cols : brokers — the union of `route.broker` across the live route list,
 *          which is exactly the same source the Modify-Route dialog uses for
 *          its broker dropdown (see `RouteTable.tsx → availableBrokers`).
 *          Discovered brokers are also persisted.
 *   Cells: a checkbox; checked = the broker is allowed for that market.
 *
 * Persistence model
 *   The backend stores a `selection` map: { market → { broker → bool } }.
 *   We treat the *keys* of that map as the persistent universe of markets
 *   and brokers. Whenever live data reveals a new market or broker, we
 *   inject it into `selection` (with a default `false` flag) and PUT the
 *   merged map back. On later reloads — even if Bloomberg data is empty —
 *   the rows/cols still render from the persisted selection.
 *
 * Edit control
 *   A single "Edit / Done" button toggles the table between read-only and
 *   editable. There is no per-row password gate.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pencil, Check, Save, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { apiService } from '@/services/api';
import type { Order, Route } from '@/types';
import { notifyMarketBrokerMappingUpdated } from '@/hooks/use-market-broker-mapping';

// ─── Types ───────────────────────────────────────────────────────────────────

type SelectionMap = Record<string, Record<string, boolean>>;

interface MappingState {
  updatedAt: string | null;
  selection: SelectionMap;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Derive the market key from an order/route record.
 *  EUR-currency exchanges collapse into the single "EUR" row. */
function deriveMarketKey(
  exchange: string | null | undefined,
  currency: string | null | undefined,
): string | null {
  const cur = (currency || '').trim().toUpperCase();
  if (cur === 'EUR') return 'EUR';
  const ex = (exchange || '').trim().toUpperCase();
  return ex || null;
}

/** Keep only Equity-style synthetic broker codes coming from EMSX's
 *  GetBrokersWithAssetClass response. The full EMSX list mixes FX/FI/MM
 *  rows that are irrelevant to the Modify-Route equity dropdown. */
function isEquityBroker(code: string): boolean {
  return /^EQ-/i.test(code.trim());
}

/** Merge live-discovered markets/brokers into the persisted selection.
 *  Returns the merged selection plus a boolean indicating whether anything
 *  changed (so the caller knows whether to PUT). */
function mergeDiscovered(
  selection: SelectionMap,
  liveMarkets: string[],
  liveBrokers: string[],
): { merged: SelectionMap; changed: boolean } {
  const merged: SelectionMap = {};
  let changed = false;

  // Universe of markets = persisted ∪ live
  const allMarkets = new Set<string>([...Object.keys(selection), ...liveMarkets]);
  // Universe of brokers = persisted (any sub-key) ∪ live
  const allBrokers = new Set<string>(liveBrokers);
  for (const sel of Object.values(selection)) for (const b of Object.keys(sel)) allBrokers.add(b);

  for (const m of allMarkets) {
    const prev = selection[m];
    if (!prev) changed = true;
    const row: Record<string, boolean> = {};
    for (const b of allBrokers) {
      if (prev && b in prev) {
        row[b] = !!prev[b];
      } else {
        row[b] = false;
        if (prev) changed = true; // new broker added to existing market row
      }
    }
    merged[m] = row;
  }
  return { merged, changed };
}

// ─── Component ───────────────────────────────────────────────────────────────

export function MarketBrokerMappingSection() {
  const [state, setState] = useState<MappingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [editMode, setEditMode] = useState(false);

  // Tracks the last selection we PUT to the backend so the auto-merge effect
  // doesn't try to push the same payload twice.
  const lastAutoSaveRef = useRef<string>('');

  const loadAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [mapResp, routesResp, ordersResp, brokersResp] = await Promise.all([
        apiService.getMarketBrokerMapping(),
        apiService.getRoutes(),
        apiService.getOrders(),
        apiService.getBrokers('EQTY'),
      ]);

      const baseSelection: SelectionMap =
        (mapResp.success && mapResp.data?.selection) || {};
      const updatedAt = (mapResp.success && mapResp.data?.updatedAt) || null;

      if (!mapResp.success) {
        setError(mapResp.error || mapResp.message || 'Failed to load mapping');
      }

      const routes: Route[] = routesResp.success && routesResp.data ? routesResp.data : [];
      const orders: Order[] = ordersResp.success && ordersResp.data ? ordersResp.data : [];

      // Discover live markets/brokers
      const liveMarkets = new Set<string>();
      for (const r of routes) {
        const k = deriveMarketKey(r.exchange, r.currency);
        if (k) liveMarkets.add(k);
      }
      for (const o of orders) {
        const k = deriveMarketKey(o.exchange, o.currency);
        if (k) liveMarkets.add(k);
      }
      const liveBrokers = new Set<string>();
      // Master list from EMSX GetBrokersWithAssetClass — filtered to the EQ-*
      // synthetic codes the Modify-Route dropdown actually offers.
      if (brokersResp.success && brokersResp.data?.brokers) {
        for (const b of brokersResp.data.brokers) {
          const code = (b || '').trim();
          if (code && isEquityBroker(code)) liveBrokers.add(code);
        }
      }
      // Union with brokers actually seen on routes — covers cases where EMSX
      // hasn't published a code yet but a real route uses it.
      for (const r of routes) {
        const b = (r.broker || '').trim();
        if (b) liveBrokers.add(b);
      }

      const { merged, changed } = mergeDiscovered(
        baseSelection,
        Array.from(liveMarkets),
        Array.from(liveBrokers),
      );

      setState({ updatedAt, selection: merged });

      // Auto-persist any newly discovered markets/brokers so they survive a
      // reload even when no live data is currently available. We don't mark
      // the form dirty here — these are passive discoveries, not user edits.
      if (changed) {
        const payload = JSON.stringify(merged);
        if (payload !== lastAutoSaveRef.current) {
          lastAutoSaveRef.current = payload;
          try {
            const resp = await apiService.updateMarketBrokerSelection(merged);
            if (resp.success && resp.data) {
              const data = resp.data as { updatedAt?: string | null };
              setState(prev =>
                prev ? { ...prev, updatedAt: data.updatedAt ?? prev.updatedAt } : prev,
              );
            }
            notifyMarketBrokerMappingUpdated(merged);
          } catch {
            // Non-fatal: persistence is best-effort here.
          }
        }
      }
    } catch (e) {
      setError((e as Error).message || 'Network error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // ── Derived: rows / cols ─────────────────────────────────────────────────
  const markets = useMemo(() => {
    if (!state) return [] as string[];
    return Object.keys(state.selection).sort();
  }, [state]);

  const brokers = useMemo(() => {
    if (!state) return [] as string[];
    const s = new Set<string>();
    for (const row of Object.values(state.selection)) {
      for (const b of Object.keys(row)) s.add(b);
    }
    return Array.from(s).sort();
  }, [state]);

  // ── Mutators ─────────────────────────────────────────────────────────────

  const toggleSelection = useCallback((market: string, broker: string) => {
    setState(prev => {
      if (!prev) return prev;
      const row = { ...(prev.selection[market] ?? {}) };
      row[broker] = !row[broker];
      return {
        ...prev,
        selection: { ...prev.selection, [market]: row },
      };
    });
    setDirty(true);
  }, []);

  const saveSelection = useCallback(async () => {
    if (!state) return;
    setSaving(true);
    try {
      const resp = await apiService.updateMarketBrokerSelection(state.selection);
      if (!resp.success) throw new Error(resp.error || resp.message || 'Save failed');
      setDirty(false);
      const data = resp.data as { updatedAt?: string | null } | undefined;
      if (data?.updatedAt) {
        setState(prev => (prev ? { ...prev, updatedAt: data.updatedAt ?? prev.updatedAt } : prev));
      }
      lastAutoSaveRef.current = JSON.stringify(state.selection);
      notifyMarketBrokerMappingUpdated(state.selection);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [state]);

  const toggleEdit = useCallback(() => {
    setEditMode(prev => !prev);
  }, []);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Market ↔ Broker Mapping</CardTitle>
            <CardDescription>
              Rows are markets discovered from real orders; columns are the same
              broker list used by the Modify-Route dialog. New markets/brokers
              are auto-persisted as they appear. Tick a cell to allow that
              broker for that market.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={loadAll} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button
              size="sm"
              variant={editMode ? 'default' : 'outline'}
              onClick={toggleEdit}
              title={editMode ? 'Switch to read-only' : 'Enable editing'}
            >
              {editMode ? (
                <><Check className="h-3.5 w-3.5 mr-1" />Done</>
              ) : (
                <><Pencil className="h-3.5 w-3.5 mr-1" />Edit</>
              )}
            </Button>
            <Button size="sm" onClick={saveSelection} disabled={!dirty || saving}>
              <Save className="h-3.5 w-3.5 mr-1" />
              {saving ? 'Saving…' : dirty ? 'Save' : 'Saved'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {error && (
          <Alert variant="destructive" className="mb-3">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <div className="flex items-center justify-between mb-2 text-[11px] text-muted-foreground">
          <span>
            {markets.length} markets · {brokers.length} brokers ·{' '}
            {editMode ? <span className="text-primary font-semibold">edit mode</span> : 'read-only'}
          </span>
          <span>
            {state?.updatedAt ? `Last saved: ${new Date(state.updatedAt).toLocaleString()}` : 'Not saved yet'}
          </span>
        </div>

        {/* Mapping table */}
        <div className="border border-border rounded-md overflow-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 sticky top-0">
              <tr>
                <th className="px-2 py-1.5 text-left w-24 border-b border-border">Market</th>
                {brokers.map(b => (
                  <th key={b} className="px-2 py-1.5 text-center font-mono whitespace-nowrap border-b border-border">
                    {b}
                  </th>
                ))}
                {brokers.length === 0 && (
                  <th className="px-2 py-1.5 text-center text-muted-foreground border-b border-border">
                    (no brokers discovered yet)
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {markets.length === 0 && (
                <tr>
                  <td
                    colSpan={1 + Math.max(brokers.length, 1)}
                    className="px-4 py-8 text-center text-muted-foreground"
                  >
                    {loading
                      ? 'Loading…'
                      : 'No markets discovered yet — load some orders/routes first, then return here.'}
                  </td>
                </tr>
              )}
              {markets.map(m => {
                const row = state?.selection[m] ?? {};
                return (
                  <tr key={m} className="border-b border-border/60 hover:bg-muted/20">
                    <td className="px-2 py-1 font-mono font-semibold">{m}</td>
                    {brokers.map(b => (
                      <td key={b} className="px-2 py-1 text-center">
                        <Checkbox
                          checked={!!row[b]}
                          disabled={!editMode}
                          onCheckedChange={() => toggleSelection(m, b)}
                        />
                      </td>
                    ))}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-[11px] text-muted-foreground">
          Click <span className="font-semibold">Edit</span> to enable the
          checkboxes, tick the allowed broker for each market, then press{' '}
          <span className="font-semibold">Save</span>. Switch to{' '}
          <span className="font-semibold">Done</span> to lock the table again.
          Use <span className="font-semibold">Refresh</span> to re-scan live
          orders for new markets/brokers.
        </p>
      </CardContent>
    </Card>
  );
}
