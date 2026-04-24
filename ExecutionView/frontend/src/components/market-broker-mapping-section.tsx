/**
 * Market Broker Mapping — Settings section.
 *
 * Rows: exchange/currency keys (EUR-currency exchanges collapse to "EUR").
 * Cols: union of all brokers across rosters.
 * Cells: checkbox — broker is allowed for that market when checked.
 *
 * Each row has a lock icon. Clicking "Edit" prompts for the admin password;
 * once verified, the row's *roster* (available-broker list) becomes editable:
 * brokers can be added or removed from the row's dropdown chip list.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { Lock, Unlock, Plus, X, Save, RefreshCw, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { apiService } from '@/services/api';

// ─── Types ───────────────────────────────────────────────────────────────────

interface MappingState {
  updatedAt: string | null;
  rosters: Record<string, string[]>;
  selection: Record<string, Record<string, boolean>>;
}

const DEFAULT_MARKETS: string[] = [
  'AU', 'HK', 'JP', 'SG', 'KR', 'TW', 'CN', 'IN', 'ID', 'MY', 'TH', 'PH', 'VN',
  'US', 'CA', 'GB', 'EUR', 'CH', 'SE', 'NO', 'DK', 'AE', 'SA', 'ZA', 'BR', 'MX',
];

// ─── Component ───────────────────────────────────────────────────────────────

export function MarketBrokerMappingSection() {
  const [state, setState] = useState<MappingState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  // Row-lock state: marketKey → unlocked?
  const [unlocked, setUnlocked] = useState<Set<string>>(new Set());

  // Password dialog state
  const [pwdDialogOpen, setPwdDialogOpen] = useState(false);
  const [pwdInput, setPwdInput] = useState('');
  const [pwdError, setPwdError] = useState<string | null>(null);
  const [pendingUnlockMarket, setPendingUnlockMarket] = useState<string | null>(null);

  // Add-broker inline state: marketKey → typed value
  const [addDraft, setAddDraft] = useState<Record<string, string>>({});

  // Add-market inline state
  const [newMarket, setNewMarket] = useState('');

  const loadState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await apiService.getMarketBrokerMapping();
      if (resp.success && resp.data) {
        const raw = resp.data;
        // Seed empty rosters for default markets so the table renders something
        // on first load; user edits persist via PUT.
        const rosters: Record<string, string[]> = { ...raw.rosters };
        const selection: Record<string, Record<string, boolean>> = { ...raw.selection };
        for (const m of DEFAULT_MARKETS) {
          if (!(m in rosters)) rosters[m] = [];
          if (!(m in selection)) selection[m] = {};
        }
        setState({ updatedAt: raw.updatedAt, rosters, selection });
      } else {
        setError(resp.message || 'Failed to load mapping');
      }
    } catch (e) {
      setError((e as Error).message || 'Network error');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadState(); }, [loadState]);

  // Derived: union of all brokers = column set
  const allBrokers = useMemo(() => {
    if (!state) return [] as string[];
    const s = new Set<string>();
    for (const list of Object.values(state.rosters)) for (const b of list) s.add(b);
    return Array.from(s).sort();
  }, [state]);

  const markets = useMemo(() => {
    if (!state) return [] as string[];
    return Object.keys(state.rosters).sort();
  }, [state]);

  // ── Mutators ─────────────────────────────────────────────────────────────

  const toggleSelection = useCallback((market: string, broker: string) => {
    setState(prev => {
      if (!prev) return prev;
      const sel = { ...(prev.selection[market] ?? {}) };
      sel[broker] = !sel[broker];
      return {
        ...prev,
        selection: { ...prev.selection, [market]: sel },
      };
    });
    setDirty(true);
  }, []);

  const saveSelection = useCallback(async () => {
    if (!state) return;
    setSaving(true);
    try {
      const resp = await apiService.updateMarketBrokerSelection(state.selection);
      if (!resp.success) throw new Error(resp.message || 'Save failed');
      setDirty(false);
      await loadState();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [state, loadState]);

  // ── Lock / unlock ────────────────────────────────────────────────────────

  const requestUnlock = useCallback((market: string) => {
    setPendingUnlockMarket(market);
    setPwdInput('');
    setPwdError(null);
    setPwdDialogOpen(true);
  }, []);

  const confirmUnlock = useCallback(async () => {
    if (!pendingUnlockMarket) return;
    try {
      const resp = await apiService.unlockMarketBrokerRow(pwdInput, pendingUnlockMarket);
      if (!resp.success || !resp.data?.unlocked) throw new Error(resp.message || 'Invalid password');
      setUnlocked(prev => {
        const n = new Set(prev);
        n.add(pendingUnlockMarket);
        return n;
      });
      // Keep password in memory (component-local) for later roster PUTs
      sessionStorage.setItem(`mbm_pw_${pendingUnlockMarket}`, pwdInput);
      setPwdDialogOpen(false);
    } catch (e) {
      setPwdError((e as Error).message || 'Invalid password');
    }
  }, [pwdInput, pendingUnlockMarket]);

  const lockRow = useCallback((market: string) => {
    setUnlocked(prev => {
      const n = new Set(prev);
      n.delete(market);
      return n;
    });
    sessionStorage.removeItem(`mbm_pw_${market}`);
  }, []);

  const pushRosterUpdate = useCallback(async (market: string, brokers: string[]) => {
    const pw = sessionStorage.getItem(`mbm_pw_${market}`) || '';
    if (!pw) {
      setError(`Row "${market}" is locked — unlock first`);
      return;
    }
    try {
      const resp = await apiService.updateMarketBrokerRoster(market, brokers, pw);
      if (!resp.success) throw new Error(resp.message || 'Roster update failed');
      await loadState();
    } catch (e) {
      setError((e as Error).message);
    }
  }, [loadState]);

  const addBrokerToMarket = useCallback((market: string) => {
    const draft = (addDraft[market] ?? '').trim().toUpperCase();
    if (!draft) return;
    if (!state) return;
    const roster = state.rosters[market] ?? [];
    if (roster.includes(draft)) return;
    const next = [...roster, draft];
    setAddDraft(prev => ({ ...prev, [market]: '' }));
    pushRosterUpdate(market, next);
  }, [addDraft, state, pushRosterUpdate]);

  const removeBrokerFromMarket = useCallback((market: string, broker: string) => {
    if (!state) return;
    const roster = state.rosters[market] ?? [];
    const next = roster.filter(b => b !== broker);
    pushRosterUpdate(market, next);
  }, [state, pushRosterUpdate]);

  const addMarket = useCallback(() => {
    const key = newMarket.trim().toUpperCase();
    if (!key) return;
    setState(prev => {
      if (!prev) return prev;
      if (key in prev.rosters) return prev;
      return {
        ...prev,
        rosters: { ...prev.rosters, [key]: [] },
        selection: { ...prev.selection, [key]: {} },
      };
    });
    setNewMarket('');
  }, [newMarket]);

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-base">Market \u2194 Broker Mapping</CardTitle>
            <CardDescription>
              Each market lists its allowed brokers; only checked brokers appear in the
              Modify-Route picker. EUR-currency exchanges share the "EUR" row.
            </CardDescription>
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={loadState} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 mr-1 ${loading ? 'animate-spin' : ''}`} />
              Refresh
            </Button>
            <Button size="sm" onClick={saveSelection} disabled={!dirty || saving}>
              <Save className="h-3.5 w-3.5 mr-1" />
              {saving ? 'Saving…' : dirty ? 'Save selection' : 'Saved'}
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

        {/* Add new market row */}
        <div className="flex items-center gap-2 mb-3">
          <Input
            placeholder="New market key (e.g. AU, JP, EUR)"
            value={newMarket}
            onChange={(e) => setNewMarket(e.target.value)}
            className="h-8 w-60 text-xs"
          />
          <Button size="sm" variant="outline" onClick={addMarket}>
            <Plus className="h-3 w-3 mr-1" />Add market
          </Button>
          <span className="text-[11px] text-muted-foreground ml-auto">
            {state?.updatedAt ? `Last saved: ${new Date(state.updatedAt).toLocaleString()}` : 'Not saved yet'}
          </span>
        </div>

        {/* Mapping table */}
        <div className="border border-border rounded-md overflow-auto">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 sticky top-0">
              <tr>
                <th className="px-2 py-1.5 text-left w-10 border-b border-border">Edit</th>
                <th className="px-2 py-1.5 text-left w-20 border-b border-border">Market</th>
                <th className="px-2 py-1.5 text-left w-64 border-b border-border">Available brokers (roster)</th>
                {allBrokers.map(b => (
                  <th key={b} className="px-2 py-1.5 text-center font-mono whitespace-nowrap border-b border-border">
                    {b}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {markets.length === 0 && (
                <tr>
                  <td colSpan={3 + allBrokers.length} className="px-4 py-8 text-center text-muted-foreground">
                    {loading ? 'Loading…' : 'No markets configured yet — add one above.'}
                  </td>
                </tr>
              )}
              {markets.map(m => {
                const roster = state?.rosters[m] ?? [];
                const sel = state?.selection[m] ?? {};
                const isUnlocked = unlocked.has(m);
                return (
                  <tr key={m} className="border-b border-border/60 hover:bg-muted/20">
                    {/* Lock / unlock */}
                    <td className="px-2 py-1">
                      {isUnlocked ? (
                        <button
                          title="Lock this row"
                          onClick={() => lockRow(m)}
                          className="text-green-600 hover:text-green-700"
                        >
                          <Unlock className="h-3.5 w-3.5" />
                        </button>
                      ) : (
                        <button
                          title="Unlock to edit roster (password required)"
                          onClick={() => requestUnlock(m)}
                          className="text-muted-foreground hover:text-foreground"
                        >
                          <Lock className="h-3.5 w-3.5" />
                        </button>
                      )}
                    </td>
                    {/* Market key */}
                    <td className="px-2 py-1 font-mono font-semibold">{m}</td>
                    {/* Roster chip list */}
                    <td className="px-2 py-1">
                      <div className="flex flex-wrap items-center gap-1">
                        {roster.length === 0 && (
                          <span className="text-[11px] text-muted-foreground italic">empty</span>
                        )}
                        {roster.map(b => (
                          <Badge key={b} variant="secondary" className="h-5 text-[10px] font-mono gap-1">
                            {b}
                            {isUnlocked && (
                              <button
                                onClick={() => removeBrokerFromMarket(m, b)}
                                className="ml-0.5 hover:text-destructive"
                                title="Remove from roster"
                              >
                                <X className="h-2.5 w-2.5" />
                              </button>
                            )}
                          </Badge>
                        ))}
                        {isUnlocked && (
                          <div className="flex items-center gap-1">
                            <Input
                              placeholder="add broker"
                              value={addDraft[m] ?? ''}
                              onChange={(e) => setAddDraft(prev => ({ ...prev, [m]: e.target.value }))}
                              onKeyDown={(e) => { if (e.key === 'Enter') addBrokerToMarket(m); }}
                              className="h-6 w-28 text-[10px] font-mono"
                            />
                            <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => addBrokerToMarket(m)}>
                              <Plus className="h-3 w-3" />
                            </Button>
                          </div>
                        )}
                      </div>
                    </td>
                    {/* Selection cells */}
                    {allBrokers.map(b => {
                      const inRoster = roster.includes(b);
                      if (!inRoster) {
                        return (
                          <td key={b} className="px-2 py-1 text-center text-muted-foreground/30">
                            \u2013
                          </td>
                        );
                      }
                      return (
                        <td key={b} className="px-2 py-1 text-center">
                          <Checkbox
                            checked={!!sel[b]}
                            onCheckedChange={() => toggleSelection(m, b)}
                          />
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <p className="mt-3 text-[11px] text-muted-foreground">
          Selection edits (checkboxes) are saved with the Save button. Roster edits
          (chips) are persisted immediately but require the row to be unlocked.
        </p>
      </CardContent>

      {/* Password dialog */}
      <Dialog open={pwdDialogOpen} onOpenChange={setPwdDialogOpen}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Unlock roster editing</DialogTitle>
            <DialogDescription>
              Enter the admin password to edit the available-broker list for
              <span className="font-mono font-semibold"> {pendingUnlockMarket}</span>.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="mbm-pwd">Password</Label>
            <Input
              id="mbm-pwd"
              type="password"
              value={pwdInput}
              onChange={(e) => { setPwdInput(e.target.value); setPwdError(null); }}
              onKeyDown={(e) => { if (e.key === 'Enter') confirmUnlock(); }}
              autoFocus
            />
            {pwdError && (
              <div className="text-xs text-destructive">{pwdError}</div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setPwdDialogOpen(false)}>Cancel</Button>
            <Button onClick={confirmUnlock}>Unlock</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
