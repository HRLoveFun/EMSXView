import { Button } from '@/components/ui/button';
import type { BrokerRatioBarProps } from './types';

export function BrokerRatioBar({
  selectedBrokers,
  ratios,
  ratioSum,
  ratioTotalValid,
  editable,
  setRatioForBroker,
  resetRatios,
  applyRatios,
}: BrokerRatioBarProps) {
  if (selectedBrokers.length === 0 || !editable) return null;

  return (
    <div className="border border-border rounded p-2 space-y-1.5 bg-secondary/20">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-muted-foreground">Allocation ratios</span>
        <div className="flex items-center gap-2">
          <span className={`text-xs font-mono font-semibold ${ratioTotalValid ? 'text-emerald-600' : 'text-red-600'}`}>
            Total = {ratioSum}% {ratioTotalValid ? '\u2705' : '\u274C'}
          </span>
          <button type="button" onClick={resetRatios}
            className="text-[11px] text-primary hover:underline">Reset to equal</button>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {selectedBrokers.map(b => {
          const pct = ratios[b] ?? 0;
          return (
            <div key={b} className="flex items-center gap-1.5 min-w-[180px]">
              <span className="text-[11px] font-mono text-muted-foreground w-24 truncate" title={b}>{b}</span>
              <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden max-w-[80px]">
                <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
              </div>
              <button type="button" onClick={() => setRatioForBroker(b, pct - 1)}
                className="h-5 w-5 inline-flex items-center justify-center rounded border border-border text-[11px] hover:bg-accent disabled:opacity-30">{'\u2212'}</button>
              <input type="number" value={pct}
                onChange={e => setRatioForBroker(b, Number(e.target.value))}
                className="h-5 w-14 text-[11px] font-mono text-center border border-border rounded bg-background" />
              <button type="button" onClick={() => setRatioForBroker(b, pct + 1)}
                className="h-5 w-5 inline-flex items-center justify-center rounded border border-border text-[11px] hover:bg-accent disabled:opacity-30">+</button>
            </div>
          );
        })}
        <Button variant="outline" size="sm" className="h-6 px-3 text-xs ml-auto"
          disabled={!ratioTotalValid}
          onClick={applyRatios}>
          Apply ratios
        </Button>
      </div>
    </div>
  );
}
