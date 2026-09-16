import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { tifOptions } from './types';
import type { TimeInForce } from '@execution/types';
import type { BatchRouteToolbarProps } from './types';

export function BatchRouteToolbar({
  tif,
  notes,
  releaseTime,
  startTime,
  endTime,
  editable,
  selectedBrokers,
  onTifChange,
  onNotesChange,
  onReleaseTimeChange,
  onStartTimeChange,
  onEndTimeChange,
  onApplyTimeToAll,
}: BatchRouteToolbarProps) {
  return (
    <>
      {/* ── TIF + notes ─────────────────────────────────────────── */}
      <div className="grid grid-cols-3 gap-3">
        <div>
          <Label className="text-xs">TIF (all routes)</Label>
          <Select value={tif} onValueChange={(v) => onTifChange(v as TimeInForce)} disabled={!editable}>
            <SelectTrigger className="h-8"><SelectValue /></SelectTrigger>
            <SelectContent>
              {tifOptions.map(t => <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="col-span-2">
          <Label className="text-xs">Notes</Label>
          <Input value={notes} onChange={(e) => onNotesChange(e.target.value)}
            className="h-8" disabled={!editable} />
        </div>
      </div>

      {/* ── RlsTm + Start / End time ────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 px-2 py-1.5 bg-secondary/30 border border-border rounded text-xs">
        <span className="text-muted-foreground">RlsTm:</span>
        <Input
          type="text"
          placeholder="HH:MM"
          value={releaseTime}
          onChange={e => onReleaseTimeChange(e.target.value)}
          className="h-6 w-20 text-xs font-mono"
          disabled={!editable}
          title="Release time (HH:MM) \u2014 sent as EMSX_RELEASE_TIME on every route"
        />
        <span className="text-[10px] font-semibold text-red-600 dark:text-red-400">exch time</span>
        <div className="w-px h-4 bg-border mx-1" />
        <span className="text-muted-foreground mr-1">Start / End time:</span>
        <Input
          type="text"
          placeholder="HH:MM:SS"
          value={startTime}
          onChange={e => onStartTimeChange(e.target.value)}
          className="h-6 w-[88px] text-xs font-mono border-emerald-400/60 dark:border-emerald-600/60 focus-visible:ring-emerald-400/30"
          disabled={!editable || selectedBrokers.length === 0}
          title="Start time (HH:MM:SS) \u2014 applied to all selected brokers"
        />
        <span className="text-muted-foreground/50">~</span>
        <Input
          type="text"
          placeholder="HH:MM:SS"
          value={endTime}
          onChange={e => onEndTimeChange(e.target.value)}
          className="h-6 w-[88px] text-xs font-mono border-rose-400/60 dark:border-rose-600/60 focus-visible:ring-rose-400/30"
          disabled={!editable || selectedBrokers.length === 0}
          title="End time (HH:MM:SS) \u2014 applied to all selected brokers"
        />
        <span className="text-[10px] font-semibold text-red-600 dark:text-red-400">local time</span>
        <Button
          variant="outline"
          size="sm"
          className="h-6 px-2 text-xs"
          onClick={onApplyTimeToAll}
          disabled={!editable || selectedBrokers.length === 0 || (!startTime && !endTime)}
        >
          Apply to all
        </Button>
      </div>
    </>
  );
}
