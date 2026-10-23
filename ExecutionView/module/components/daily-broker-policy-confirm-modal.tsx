/**
 * DailyBrokerPolicyConfirmModal（057 DL-17a/071）
 *
 * 券商市场准入白名单的每日确认（用户 2026-10-23 决策：候选自动拉取 + 每日
 * 当地 08:00 后首次打开弹窗确认）。数据源为既有 `market_broker_mapping`
 * （rosters = 按市场候选券商；selection = 每券商准入开关）；确认即回写
 * selection 刷新 updatedAt（当日不再弹）。
 *
 * 本会话内「稍后处理」只隐藏当前会话（sessionStorage），不写后端。
 */
import { useEffect, useMemo, useState } from 'react';

import { routesApi } from '@execution/services/routes-api';

type MappingData = {
  updatedAt: string | null;
  rosters: Record<string, string[]>;
  selection: Record<string, Record<string, boolean>>;
};

const SESSION_SKIP_KEY = 'broker-policy-confirm:skipped';
const CONFIRM_HOUR = 8;

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

function needsConfirmation(updatedAt: string | null): boolean {
  if (sessionStorage.getItem(SESSION_SKIP_KEY)) {
    return false; // 本会话已选择「稍后处理」
  }
  if (new Date().getHours() < CONFIRM_HOUR) {
    return false;
  }
  const confirmedDate = updatedAt ? new Date(updatedAt).toISOString().slice(0, 10) : null;
  return confirmedDate !== todayIso();
}

export const DailyBrokerPolicyConfirmModal = () => {
  const [data, setData] = useState<MappingData | null>(null);
  const [draft, setDraft] = useState<Record<string, Record<string, boolean>>>({});
  const [visible, setVisible] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    routesApi
      .getMarketBrokerMapping()
      .then((resp) => {
        if (cancelled || !resp.success || !resp.data) return;
        const next = resp.data as MappingData;
        setData(next);
        setDraft(next.selection ?? {});
        setVisible(needsConfirmation(next.updatedAt));
      })
      .catch(() => {
        /* 映射不可用时不打扰用户（设置页仍可手动维护） */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const markets = useMemo(() => {
    if (!data) return [];
    return Object.keys(data.rosters ?? {}).sort();
  }, [data]);

  if (!visible || !data || markets.length === 0) {
    return null;
  }

  const toggle = (market: string, broker: string) => {
    setDraft((prev) => ({
      ...prev,
      [market]: { ...(prev[market] ?? {}), [broker]: !prev[market]?.[broker] },
    }));
  };

  const skip = () => {
    sessionStorage.setItem(SESSION_SKIP_KEY, todayIso());
    setVisible(false);
  };

  const confirm = async () => {
    setSaving(true);
    setError(null);
    try {
      const resp = await routesApi.updateMarketBrokerSelection(draft);
      if (!resp.success) {
        throw new Error(resp.error || 'Failed to save broker policy');
      }
      window.dispatchEvent(new CustomEvent('market-broker-mapping:updated'));
      setVisible(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="max-h-[80vh] w-full max-w-2xl overflow-y-auto rounded-2xl border bg-card p-6 shadow-xl">
        <p className="text-sm font-semibold text-foreground">Daily broker access confirmation</p>
        <p className="mt-1 text-xs text-muted-foreground">
          按市场确认今日可路由的券商（候选来自 Market Broker Mapping 的 rosters；确认后写回
          selection 并刷新确认时间）。未选中的券商今日不可路由。
        </p>

        <div className="mt-4 space-y-3">
          {markets.map((market) => {
            const brokers = data.rosters[market] ?? [];
            const selected = draft[market] ?? {};
            return (
              <div key={market} className="rounded-xl border border-border p-3">
                <p className="text-xs font-medium text-foreground">{market}</p>
                <div className="mt-2 flex flex-wrap gap-2">
                  {brokers.length === 0 ? (
                    <span className="text-xs text-muted-foreground">No brokers in roster</span>
                  ) : (
                    brokers.map((broker) => (
                      <label
                        key={broker}
                        className={`inline-flex cursor-pointer items-center gap-1 rounded-full border px-2 py-1 text-[11px] ${
                          selected[broker] ? 'border-emerald-500/40 bg-emerald-500/10' : 'border-border bg-muted/30'
                        }`}
                      >
                        <input
                          type="checkbox"
                          className="h-3 w-3"
                          checked={Boolean(selected[broker])}
                          onChange={() => toggle(market, broker)}
                        />
                        {broker}
                      </label>
                    ))
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {error ? <p className="mt-3 text-xs text-red-700">{error}</p> : null}

        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground"
            onClick={skip}
            disabled={saving}
          >
            稍后处理
          </button>
          <button
            type="button"
            className="rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground disabled:opacity-60"
            onClick={confirm}
            disabled={saving}
          >
            {saving ? 'Saving…' : '确认今日券商准入'}
          </button>
        </div>
      </div>
    </div>
  );
};
