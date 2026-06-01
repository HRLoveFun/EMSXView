import { useState, useCallback } from 'react';
import { FileEdit, Plus, Trash2 } from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import {
  BROKER_VOLUME_CAP_FIELD,
} from '@execution/data/broker-volume-cap-mapping';

const STORAGE_KEY = 'emsx_volume_cap_mapping_overrides';

interface MappingEntry {
  broker: string;
  strategy: string;
  field: string;
}

function loadOverrides(): Record<string, Record<string, string>> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveOverrides(data: Record<string, Record<string, string>>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
}

function buildEntries(
  base: Record<string, Record<string, string>>,
  overrides: Record<string, Record<string, string>>,
): MappingEntry[] {
  const entries: MappingEntry[] = [];
  const seen = new Set<string>();
  const merged: Record<string, Record<string, string>> = {};

  for (const b of Object.keys(base)) {
    merged[b] = { ...base[b] };
  }
  for (const b of Object.keys(overrides)) {
    merged[b] = { ...(merged[b] ?? {}), ...overrides[b] };
  }

  for (const b of Object.keys(merged).sort()) {
    for (const s of Object.keys(merged[b]).sort()) {
      const key = `${b}#${s}`;
      seen.add(key);
      entries.push({ broker: b, strategy: s, field: merged[b][s] });
    }
  }
  for (const b of Object.keys(overrides)) {
    for (const s of Object.keys(overrides[b])) {
      const key = `${b}#${s}`;
      if (!seen.has(key) && overrides[b][s]) {
        entries.push({ broker: b, strategy: s, field: overrides[b][s] });
      }
    }
  }
  return entries;
}

interface VolumeCapMappingEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function VolumeCapMappingEditor({ open, onOpenChange }: VolumeCapMappingEditorProps) {
  const [overrides, setOverrides] = useState<Record<string, Record<string, string>>>(loadOverrides);
  const [newBroker, setNewBroker] = useState('');
  const [newStrategy, setNewStrategy] = useState('');
  const [newField, setNewField] = useState('');

  const entries = buildEntries(BROKER_VOLUME_CAP_FIELD, overrides);

  const handleFieldChange = useCallback((broker: string, strategy: string, value: string) => {
    setOverrides(prev => {
      const next = { ...prev };
      if (!next[broker]) next[broker] = {};
      if (value) {
        next[broker][strategy] = value;
      } else {
        delete next[broker][strategy];
        if (Object.keys(next[broker]).length === 0) delete next[broker];
      }
      return next;
    });
  }, []);

  const handleAdd = useCallback(() => {
    const b = newBroker.trim().toUpperCase();
    const s = newStrategy.trim();
    const f = newField.trim();
    if (!b || !s) return;
    handleFieldChange(b, s, f);
    setNewBroker('');
    setNewStrategy('');
    setNewField('');
  }, [newBroker, newStrategy, newField, handleFieldChange]);

  const handleDelete = useCallback((broker: string, strategy: string) => {
    handleFieldChange(broker, strategy, '');
  }, [handleFieldChange]);

  const handleSave = useCallback(() => {
    saveOverrides(overrides);
    onOpenChange(false);
  }, [overrides, onOpenChange]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileEdit className="h-5 w-5" />
            Volume Cap Field Mapping
          </DialogTitle>
          <DialogDescription>
            Broker &rarr; Strategy &rarr; field name mapping used to auto-set
            volume cap after validation. Edit field names below; changes are
            saved to local storage.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 py-4">
          <div className="text-xs text-muted-foreground">
            {entries.length} entries across {new Set(entries.map(e => e.broker)).size} brokers
          </div>

          <div className="border border-border rounded overflow-hidden">
            <div className="grid grid-cols-[1fr_1fr_2fr_40px] gap-0 text-[11px] font-semibold text-muted-foreground bg-muted px-3 py-1.5 border-b border-border">
              <div>Broker</div>
              <div>Strategy</div>
              <div>Volume Cap Field</div>
              <div />
            </div>
            <div className="max-h-64 overflow-y-auto divide-y divide-border">
              {entries.map(({ broker, strategy, field }) => {
                const isOverridden = overrides[broker]?.[strategy] !== undefined;
                const isDefault = !isOverridden && BROKER_VOLUME_CAP_FIELD[broker]?.[strategy] !== undefined;
                return (
                  <div
                    key={`${broker}#${strategy}`}
                    className={`grid grid-cols-[1fr_1fr_2fr_40px] gap-0 px-3 py-1 items-center text-xs ${
                      isOverridden ? 'bg-amber-50 dark:bg-amber-950/20' : ''
                    }`}
                  >
                    <div className="font-mono truncate">{broker}</div>
                    <div className="truncate">{strategy || <span className="italic text-muted-foreground">(any)</span>}</div>
                    <div>
                      <Input
                        value={field}
                        onChange={e => handleFieldChange(broker, strategy, e.target.value)}
                        placeholder="(no mapping)"
                        className="h-7 text-xs font-mono"
                      />
                    </div>
                    <div className="flex justify-center">
                      {isDefault && (
                        <button
                          type="button"
                          onClick={() => handleDelete(broker, strategy)}
                          className="text-muted-foreground hover:text-destructive p-0.5"
                          title="Remove"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="border border-border rounded p-2 space-y-2">
            <div className="text-xs font-semibold text-muted-foreground">Add entry</div>
            <div className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-end">
              <div>
                <Input
                  value={newBroker}
                  onChange={e => setNewBroker(e.target.value.toUpperCase())}
                  placeholder="Broker code"
                  className="h-7 text-xs font-mono"
                />
              </div>
              <div>
                <Input
                  value={newStrategy}
                  onChange={e => setNewStrategy(e.target.value)}
                  placeholder="Strategy name"
                  className="h-7 text-xs"
                />
              </div>
              <div>
                <Input
                  value={newField}
                  onChange={e => setNewField(e.target.value)}
                  placeholder="Field name"
                  className="h-7 text-xs"
                />
              </div>
              <Button
                size="sm"
                variant="outline"
                onClick={handleAdd}
                disabled={!newBroker.trim() || !newStrategy.trim()}
                className="h-7"
              >
                <Plus className="h-3 w-3" />
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSave}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
