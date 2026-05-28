import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, RotateCcw, Save, Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { createDefaultCostViewConfig, getSeverityText, getSeverityTone } from '../lib/thresholds';
import type { CostViewConfig, ExportDefaults, ThresholdRule } from '../types';

interface ConfigureViewProps {
  config: CostViewConfig;
  onSave: (config: CostViewConfig) => void;
}

function downloadJsonFile(value: unknown, fileName: string) {
  const blob = new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

export function ConfigureView({ config, onSave }: ConfigureViewProps) {
  const [draft, setDraft] = useState<CostViewConfig>(config);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    setDraft(config);
  }, [config]);

  const isDirty = useMemo(() => JSON.stringify(draft) !== JSON.stringify(config), [config, draft]);

  function updateRule(ruleKey: keyof CostViewConfig['rules'], nextRule: ThresholdRule) {
    setDraft((current) => ({
      ...current,
      rules: {
        ...current.rules,
        [ruleKey]: nextRule,
      },
      updatedAt: new Date().toISOString(),
    }));
  }

  function updateExportDefaults(nextDefaults: Partial<ExportDefaults>) {
    setDraft((current) => ({
      ...current,
      exportDefaults: {
        ...current.exportDefaults,
        ...nextDefaults,
      },
      updatedAt: new Date().toISOString(),
    }));
  }

  async function handleImport(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = JSON.parse(text) as CostViewConfig;
      setDraft({
        ...createDefaultCostViewConfig(),
        ...parsed,
        rules: {
          ...createDefaultCostViewConfig().rules,
          ...(parsed.rules ?? {}),
        },
        exportDefaults: {
          ...createDefaultCostViewConfig().exportDefaults,
          ...(parsed.exportDefaults ?? {}),
        },
      });
    } catch {
      window.alert('Failed to import CostView configuration.');
    } finally {
      event.target.value = '';
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-3 rounded-xl border bg-card p-5 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-xl font-semibold">Configure Alerts & Export</h2>
          <p className="text-sm text-muted-foreground">Tune metric thresholds, severity rules, and default export behavior.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <input ref={fileInputRef} type="file" accept="application/json" className="hidden" onChange={handleImport} />
          <Button variant="outline" onClick={() => downloadJsonFile(draft, `costview-config-${new Date().toISOString().slice(0, 10)}.json`)}><Download className="mr-2 h-4 w-4" />Export Config</Button>
          <Button variant="outline" onClick={() => fileInputRef.current?.click()}><Upload className="mr-2 h-4 w-4" />Import Config</Button>
          <Button variant="outline" onClick={() => setDraft(createDefaultCostViewConfig())}><RotateCcw className="mr-2 h-4 w-4" />Reset Defaults</Button>
          <Button onClick={() => onSave({ ...draft, updatedAt: new Date().toISOString() })} disabled={!isDirty}><Save className="mr-2 h-4 w-4" />Save</Button>
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Threshold Rules</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[920px] text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-3 pr-3 text-left font-medium">Metric</th>
                  <th className="py-3 pr-3 text-left font-medium">Mode</th>
                  <th className="py-3 pr-3 text-right font-medium">Warning</th>
                  <th className="py-3 pr-3 text-right font-medium">Critical</th>
                  <th className="py-3 pr-3 text-left font-medium">Enabled</th>
                  <th className="py-3 text-left font-medium">Preview</th>
                </tr>
              </thead>
              <tbody>
                {Object.values(draft.rules).map((rule) => (
                  <tr key={rule.key} className="border-b border-border/40 last:border-b-0">
                    <td className="py-3 pr-3 align-top">
                      <div className="font-medium">{rule.label}</div>
                      <div className="mt-1 text-xs text-muted-foreground">{rule.description}</div>
                    </td>
                    <td className="py-3 pr-3 align-top">
                      <select className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm" value={rule.mode} onChange={(event) => updateRule(rule.key, { ...rule, mode: event.target.value as ThresholdRule['mode'] })}>
                        <option value="absolute-above">Absolute above</option>
                        <option value="above">Above</option>
                        <option value="below">Below</option>
                      </select>
                    </td>
                    <td className="py-3 pr-3 align-top text-right">
                      <input type="number" step="0.1" className="w-28 rounded-md border border-input bg-background px-3 py-2 text-right text-sm" value={rule.warningThreshold} onChange={(event) => updateRule(rule.key, { ...rule, warningThreshold: Number(event.target.value) })} />
                    </td>
                    <td className="py-3 pr-3 align-top text-right">
                      <input type="number" step="0.1" className="w-28 rounded-md border border-input bg-background px-3 py-2 text-right text-sm" value={rule.criticalThreshold} onChange={(event) => updateRule(rule.key, { ...rule, criticalThreshold: Number(event.target.value) })} />
                    </td>
                    <td className="py-3 pr-3 align-top">
                      <label className="inline-flex items-center gap-2 text-sm">
                        <input type="checkbox" checked={rule.enabled} onChange={(event) => updateRule(rule.key, { ...rule, enabled: event.target.checked })} />
                        Enabled
                      </label>
                    </td>
                    <td className="py-3 align-top">
                      <div className="flex flex-wrap gap-2">
                        <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('normal')}`}>{getSeverityText('normal')}</span>
                        <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('warning')}`}>{getSeverityText('warning')}</span>
                        <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('critical')}`}>{getSeverityText('critical')}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Export Defaults</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Default format</span>
              <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={draft.exportDefaults.format} onChange={(event) => updateExportDefaults({ format: event.target.value as ExportDefaults['format'] })}>
                <option value="csv">CSV</option>
                <option value="excel">Excel</option>
                <option value="pdf">PDF</option>
              </select>
            </label>
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground">Default scope</span>
              <select className="w-full rounded-md border border-input bg-background px-3 py-2" value={draft.exportDefaults.scope} onChange={(event) => updateExportDefaults({ scope: event.target.value as ExportDefaults['scope'] })}>
                <option value="current-page">Current page</option>
                <option value="all-filtered">All filtered results</option>
                <option value="selected-order">Selected order</option>
              </select>
            </label>
            <label className="col-span-full flex items-center gap-3 rounded-lg border border-border p-3 text-sm">
              <input type="checkbox" checked={draft.exportDefaults.pdfIncludeCharts} onChange={(event) => updateExportDefaults({ pdfIncludeCharts: event.target.checked })} />
              <span>Reserve chart snapshots for PDF export when chart capture support is added</span>
            </label>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Preview</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg border border-border bg-muted/20 p-3">
              <div className="text-xs text-muted-foreground">Sample Order</div>
              <div className="mt-1 font-mono text-sm">ORDER-123456</div>
              <div className="mt-2 flex flex-wrap gap-2">
                <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('normal')}`}>Tracking Error 6.0 bps</span>
                <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('warning')}`}>Fill % 72.0%</span>
                <span className={`inline-flex rounded border px-2 py-0.5 text-xs ${getSeverityTone('critical')}`}>Vol % ADV20 12.5%</span>
              </div>
            </div>
            <div className="text-xs text-muted-foreground">Saved settings are stored in this browser only. Export the configuration JSON if you want to reuse the same alert rules elsewhere.</div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}