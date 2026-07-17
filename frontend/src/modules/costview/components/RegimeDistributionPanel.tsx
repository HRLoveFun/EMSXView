import { useEffect, useMemo, useReducer, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { fetchRegimeDistribution, type RegimeDistributionRow } from '../services/api';

type RegimeDim = 'vol_regime' | 'liq_regime' | 'trend_regime';

const REGIME_COLORS: Record<string, string> = {
  low: '#10b981',     // green
  normal: '#3b82f6',  // blue
  high: '#f59e0b',    // amber
  extreme: '#ef4444', // red
  none: '#9ca3af',    // gray
};

interface Props {
  startDate: string; // YYYY-MM-DD
  endDate: string;   // YYYY-MM-DD
  marketCode?: string; // optional filter; default "all"
}

interface ChartSlot {
  date: string;
  low: number;
  normal: number;
  high: number;
  extreme: number;
  none: number;
}

interface RegimeKeys {
  keys: ReadonlyArray<keyof RegimeDistributionRow>;
}

const VOL_LIQ_KEYS: RegimeKeys = { keys: ['low', 'normal', 'high', 'extreme', 'none'] as const };

interface FetchState {
  rows: RegimeDistributionRow[];
  loading: boolean;
  error: string | null;
  configVersion: string | null;
}

type FetchAction =
  | { type: 'start' }
  | { type: 'success'; rows: RegimeDistributionRow[]; configVersion: string | null }
  | { type: 'error'; message: string };

const initialFetchState: FetchState = {
  rows: [],
  loading: true,
  error: null,
  configVersion: null,
};

function fetchReducer(state: FetchState, action: FetchAction): FetchState {
  switch (action.type) {
    case 'start':
      return { ...state, loading: true, error: null };
    case 'success':
      return { rows: action.rows, loading: false, error: null, configVersion: action.configVersion };
    case 'error':
      return { ...state, loading: false, error: action.message, rows: [] };
    default:
      return state;
  }
}

export function RegimeDistributionPanel({ startDate, endDate, marketCode }: Props) {
  const [regimeDim, setRegimeDim] = useState<RegimeDim>('vol_regime');
  const [state, dispatch] = useReducer(fetchReducer, initialFetchState);

  useEffect(() => {
    let cancelled = false;
    dispatch({ type: 'start' });
    fetchRegimeDistribution({ startDate, endDate, regimeDim })
      .then((res) => {
        if (cancelled) return;
        dispatch({ type: 'success', rows: res.rows, configVersion: res.config_version });
      })
      .catch((err) => {
        if (cancelled) return;
        dispatch({ type: 'error', message: err instanceof Error ? err.message : String(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [startDate, endDate, regimeDim]);

  // Aggregate across markets unless filter set; show stacked bar by date.
  const chartData = useMemo(() => {
    const bucket: Record<string, ChartSlot> = {};
    for (const r of state.rows) {
      if (marketCode && r.market_code !== marketCode) continue;
      const slot = bucket[r.date] ?? { date: r.date, low: 0, normal: 0, high: 0, extreme: 0, none: 0 };
      slot.low = (slot.low ?? 0) + r.low;
      slot.normal = (slot.normal ?? 0) + r.normal;
      slot.high = (slot.high ?? 0) + r.high;
      slot.extreme = (slot.extreme ?? 0) + r.extreme;
      slot.none = (slot.none ?? 0) + r.none;
      bucket[r.date] = slot;
    }
    return Object.values(bucket).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  }, [state.rows, marketCode]);

  const totalFills = useMemo(
    () => chartData.reduce((acc, row) => acc + (row.low + row.normal + row.high + row.extreme + row.none), 0),
    [chartData],
  );

  return (
    <div className="rounded-lg border border-gray-200 p-4 bg-white">
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-sm font-semibold">Regime distribution</h3>
          <p className="text-xs text-gray-500">
            {startDate} → {endDate}
            {marketCode ? ` · market=${marketCode}` : ' · all markets'}
            {state.configVersion ? ` · cfg=${state.configVersion}` : ''}
            {' · '}{totalFills.toLocaleString()} fills
          </p>
        </div>
        <select
          className="text-xs border rounded px-2 py-1"
          value={regimeDim}
          onChange={(e) => setRegimeDim(e.target.value as RegimeDim)}
        >
          <option value="vol_regime">vol_regime</option>
          <option value="liq_regime">liq_regime</option>
          <option value="trend_regime">trend_regime</option>
        </select>
      </div>
      {state.loading && <div className="text-xs text-gray-500">Loading…</div>}
      {state.error && <div className="text-xs text-red-600">Error: {state.error}</div>}
      {!state.loading && !state.error && chartData.length === 0 && (
        <div className="text-xs text-gray-500">No data in range.</div>
      )}
      {!state.loading && !state.error && chartData.length > 0 && (
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={chartData} margin={{ top: 8, right: 16, left: 0, bottom: 24 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis dataKey="date" tick={{ fontSize: 10 }} angle={-45} textAnchor="end" height={50} />
            <YAxis tick={{ fontSize: 10 }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {VOL_LIQ_KEYS.keys.map((k) => (
              <Bar key={k as string} dataKey={k as string} stackId="a" fill={REGIME_COLORS[k as string]} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  );
}
