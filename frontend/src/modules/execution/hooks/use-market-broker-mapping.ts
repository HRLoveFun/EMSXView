/**
 * useMarketBrokerMapping
 * ──────────────────────
 * Shared accessor for the persisted `Market Broker` allow-list configured
 * in `Settings → Market Broker Mapping`. Used by Route-Order and
 * Modify-Route dialogs to restrict their broker dropdown to the brokers the
 * desk has explicitly allowed for the order's market.
 *
 * Behaviour:
 *   • One module-level cache shared by every consumer (avoids redundant GETs).
 *   • Refreshes lazily on first mount and whenever the Settings page emits
 *     the `market-broker-mapping:updated` custom event after a save/merge.
 *   • `allowedFor(market)` returns:
 *       - `null` when no row exists for that market (caller should not
 *         restrict — the mapping has nothing to say about this market yet).
 *       - `string[]` when at least one broker is checked for that market.
 *       - `[]` when the row exists but every broker is unchecked. Callers
 *         should treat this as "nothing allowed" and decide their own
 *         fallback (e.g. show all + warn).
 */

import { useCallback, useEffect, useState } from 'react';
import { apiService } from '@execution/services/execution-api';
import { getBrokerExchangeMapping } from '@execution/data/broker-exchange-mapping';

type SelectionMap = Record<string, Record<string, boolean>>;

const EVENT_NAME = 'market-broker-mapping:updated';
const DEFAULT_MAPPING = getBrokerExchangeMapping();

let cachedSelection: SelectionMap | null = null;
let inflight: Promise<SelectionMap> | null = null;

async function fetchSelection(force = false): Promise<SelectionMap> {
  if (!force && cachedSelection) return cachedSelection;
  if (!force && inflight) return inflight;
  inflight = (async () => {
    try {
      const resp = await apiService.getMarketBrokerMapping();
      const next = resp.success && resp.data?.selection ? resp.data.selection : {};
      cachedSelection = next;
      return next;
    } catch {
      cachedSelection = cachedSelection ?? {};
      return cachedSelection;
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Notify all hook consumers that the persisted mapping has changed. */
export function notifyMarketBrokerMappingUpdated(selection?: SelectionMap): void {
  if (selection) cachedSelection = selection;
  if (typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent(EVENT_NAME));
  }
}

/** Derive the market key from an order/route record.
 *  EUR-currency exchanges collapse into the single "EUR" row. */
export function deriveMarketKey(
  exchange: string | null | undefined,
  currency: string | null | undefined,
): string | null {
  const cur = (currency || '').trim().toUpperCase();
  if (cur === 'EUR') return 'EUR';
  const ex = (exchange || '').trim().toUpperCase();
  return ex || null;
}

export interface UseMarketBrokerMappingResult {
  /** Brokers explicitly allowed for `market`, or null if no row configured.
   *  Returns an empty array if every broker for that market is unchecked. */
  allowedFor: (market: string | null | undefined) => string[] | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function useMarketBrokerMapping(): UseMarketBrokerMappingResult {
  const [selection, setSelection] = useState<SelectionMap>(() => cachedSelection ?? {});
  const [loading, setLoading] = useState<boolean>(cachedSelection === null);

  const reload = useCallback(async (force = false) => {
    setLoading(true);
    const next = await fetchSelection(force);
    setSelection(next);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (cachedSelection === null) {
      void reload(false);
    }
    const handler = () => { void reload(true); };
    window.addEventListener(EVENT_NAME, handler);
    return () => window.removeEventListener(EVENT_NAME, handler);
  }, [reload]);

  const allowedFor = useCallback(
    (market: string | null | undefined): string[] | null => {
      if (!market) return null;
      const savedRow = selection[market];
      const defaultRow = DEFAULT_MAPPING[market];
      if (!savedRow && !defaultRow) return null;

      const brokers = new Set<string>([
        ...Object.keys(savedRow || {}),
        ...Object.keys(defaultRow || {}),
      ]);

      return Array.from(brokers).filter(b => {
        if (savedRow && b in savedRow) return !!savedRow[b];
        if (defaultRow && b in defaultRow) return !!defaultRow[b];
        return false;
      });
    },
    [selection],
  );

  return { allowedFor, loading, refresh: () => reload(true) };
}

/** Apply the mapping to a candidate broker list.
 *
 * Rules:
 *   • If no row exists for `market` (allowed === null) → return `candidates`.
 *   • Otherwise return the intersection of `candidates` with `allowed`,
 *     with `currentBroker` always preserved so the dialog never hides the
 *     value the route actually has on it.
 *   • If the result would be empty, fall back to `candidates` so the user
 *     is never blocked by a misconfiguration.
 */
export function applyMappingFilter(
  candidates: string[],
  allowed: string[] | null,
  currentBroker?: string | null,
): string[] {
  if (allowed === null) return candidates;
  const allowSet = new Set(allowed);
  if (currentBroker) allowSet.add(currentBroker);
  const filtered = candidates.filter(b => allowSet.has(b));
  return filtered.length > 0 ? filtered : candidates;
}