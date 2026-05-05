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

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pencil, Check, Save, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { apiService } from '@/services/api';
import { notifyMarketBrokerMappingUpdated } from '@/hooks/use-market-broker-mapping';
import { getBrokerExchangeMapping } from '@/data/broker-exchange-mapping';
import { EXCHANGE_REGION, REGION_ORDER, REGION_LABELS } from '@/data/exchange-region-mapping';

// ─── Types ───────────────────────────────────────────────────────────────────

type SelectionMap = Record<string, Record<string, boolean>>;

interface MappingState {
  updatedAt: string | null;
  selection: SelectionMap;
}

// ─── Helpers ────────────────────────────────────────────────────────────────

/** Merge saved selection with defaults from EXCHANGE_FOR_BROKER.
 *  Saved values take precedence; defaults fill in missing markets/brokers.
 *  Only includes broker keys that exist in either `saved` or `defaults`
 *  so we don't pollute the persisted state with irrelevant false entries. */
function mergeWithDefaults(
  saved: SelectionMap,
  defaults: SelectionMap,
): SelectionMap {
  const merged: SelectionMap = {};
  const allMarkets = new Set<string>([...Object.keys(defaults), ...Object.keys(saved)]);

  for (const m of allMarkets) {
    merged[m] = {};
    const savedRow = saved[m];
    const defaultRow = defaults[m];
    // Broker keys: union of saved and defaults only
    const brokerKeys = new Set<string>([
      ...Object.keys(savedRow || {}),
      ...Object.keys(defaultRow || {}),
    ]);
    for (const b of brokerKeys) {
      if (savedRow && b in savedRow) {
        merged[m][b] = !!savedRow[b];
      } else if (defaultRow && b in defaultRow) {
        merged[m][b] = !!defaultRow[b];
      }
    }
  }
  return merged;
}

// ─── Component ───────────────────────────────────────────────────────────────

export function MarketBrokerMappingSection() {
  const [state, setState] = useState<MappingState | null>(null);
  const [defaults, setDefaults] = useState<SelectionMap>({});
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
      const mapResp = await apiService.getMarketBrokerMapping();

      const baseSelection: SelectionMap =
        (mapResp.success && mapResp.data?.selection) || {};
      const updatedAt = (mapResp.success && mapResp.data?.updatedAt) || null;

      if (!mapResp.success) {
        setError(mapResp.error || mapResp.message || 'Failed to load mapping');
      }

      const defaultMapping = getBrokerExchangeMapping();
      setDefaults(defaultMapping);
      const merged = mergeWithDefaults(baseSelection, defaultMapping);

      setState({ updatedAt, selection: merged });

      // Auto-persist if backend has no data yet so the mapping survives reloads
      if (Object.keys(baseSelection).length === 0) {
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
  // Universe is strictly defined by EXCHANGE_FOR_BROKER; users can only
  // reduce active brokers, never add new market-broker pairs.
  // Markets are grouped by region (APAC / EMEA / EUR / NSA).

  type MarketGroup = { region: string; label: string; markets: string[] };

  const marketGroups = useMemo((): MarketGroup[] => {
    const map = new Map<string, string[]>();
    for (const m of Object.keys(defaults)) {
      const region = EXCHANGE_REGION[m] || 'Other';
      if (!map.has(region)) map.set(region, []);
      map.get(region)!.push(m);
    }
    for (const arr of map.values()) arr.sort();
    // Order groups per REGION_ORDER, then any unknown groups
    const ordered: MarketGroup[] = [];
    for (const r of REGION_ORDER) {
      const items = map.get(r);
      if (items) {
        ordered.push({ region: r, label: REGION_LABELS[r], markets: items });
        map.delete(r);
      }
    }
    for (const [k, v] of Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b))) {
      ordered.push({ region: k, label: k, markets: v.sort() });
    }
    return ordered;
  }, [defaults]);

  const totalMarkets = useMemo(
    () => marketGroups.reduce((sum, g) => sum + g.markets.length, 0),
    [marketGroups],
  );

  const brokers = useMemo(() => {
    const s = new Set<string>();
    for (const row of Object.values(defaults)) {
      for (const b of Object.keys(row)) s.add(b);
    }
    return Array.from(s).sort();
  }, [defaults]);

  // ── Mutators ─────────────────────────────────────────────────────────────

  const toggleSelection = useCallback((market: string, broker: string) => {
    // Only allow reducing: the broker-market pair must exist in defaults
    // and be active; the user can only uncheck it (set to false).
    if (!defaults[market]?.[broker]) return;

    setState(prev => {
      if (!prev) return prev;
      const row = { ...(prev.selection[market] ?? {}) };
      const current = row[broker] ?? defaults[market][broker];
      // Already false — cannot add back
      if (!current) return prev;
      row[broker] = false;
      return {
        ...prev,
        selection: { ...prev.selection, [market]: row },
      };
    });
    setDirty(true);
  }, [defaults]);

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
            <CardTitle className="text-base">Market Broker Mapping</CardTitle>
            <CardDescription>
              Source: hard-coded broker-exchange mapping table.
              You may only uncheck active brokers (reduce); you cannot
              activate new broker-market pairs.
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
            {totalMarkets} markets · {brokers.length} brokers ·{' '}
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
              {marketGroups.length === 0 && (
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
              {marketGroups.map(group => (
                <Fragment key={group.region}>
                  {/* Region header row */}
                  <tr className="bg-muted/50 border-b-2 border-border">
                    <td
                      colSpan={1 + Math.max(brokers.length, 1)}
                      className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wide"
                    >
                      {group.label}
                    </td>
                  </tr>
                  {/* Market rows in this group */}
                  {group.markets.map(m => {
                    const row = state?.selection[m] ?? {};
                    return (
                      <tr key={m} className="border-b border-border/60 hover:bg-muted/20">
                        <td className="px-2 py-1 font-mono font-semibold">{m}</td>
                        {brokers.map(b => (
                          <td key={b} className="px-2 py-1 text-center">
                            <Checkbox
                              checked={!!row[b]}
                              disabled={!editMode || !defaults[m]?.[b]}
                              onCheckedChange={() => toggleSelection(m, b)}
                            />
                          </td>
                        ))}
                      </tr>
                    );
                  })}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-[11px] text-muted-foreground">
          Click <span className="font-semibold">Edit</span> to disable
          brokers for a market. Only currently active brokers can be
          unchecked; you cannot activate new broker-market pairs. Press{' '}
          <span className="font-semibold">Save</span> to persist your
          changes.
        </p>
      </CardContent>
    </Card>
  );
}
