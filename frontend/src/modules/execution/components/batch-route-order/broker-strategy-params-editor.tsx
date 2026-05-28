import { useEffect, useRef } from 'react';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  BrokerStrategyFields,
  useStrategyFields,
} from '@execution/components/broker-strategy-fields';
import type { BrokerStrategyParamsEditorProps } from './types';

export function BrokerStrategyParamsEditor({
  broker,
  strategy,
  strategies,
  onStrategyChange,
  registerParamsBuilder,
  getCachedSnapshot,
  disabled,
  registerFieldSetter,
}: BrokerStrategyParamsEditorProps) {
  const state = useStrategyFields(broker, strategy, 'EQTY');

  // Register a setter so the parent dialog can programmatically update
  // strategy parameter fields (e.g. auto-set volume cap after validate).
  useEffect(() => {
    if (!registerFieldSetter) return;
    const setter = (fieldName: string, value: string) => {
      state.setFields(prev =>
        prev.map(f =>
          f.fieldName === fieldName
            ? { ...f, value, disabled: false }
            : f,
        ),
      );
    };
    registerFieldSetter(broker, setter);
    return () => registerFieldSetter(broker, null);
  }, [broker, state.setFields, registerFieldSetter]);

  // Restore cached params after the catalog finishes loading the defaults.
  const restoredKeyRef = useRef<string>('');
  useEffect(() => {
    const key = `${broker}#${strategy}`;
    if (!strategy || state.isLoading || state.fields.length === 0) return;
    if (restoredKeyRef.current === key) return;
    const snap = getCachedSnapshot(broker, strategy);
    if (snap && snap.fields && snap.fields.length === state.fields.length) {
      state.setFields(prev => prev.map((f, i) => ({
        ...f,
        value: snap.fields[i]?.value ?? f.value,
        disabled: snap.fields[i]?.disabled ?? f.disabled,
      })));
    }
    restoredKeyRef.current = key;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [broker, strategy, state.isLoading, state.fields.length]);

  // Register a stable builder for this broker so the dialog can collect
  // strategy params at request-build time.
  useEffect(() => {
    registerParamsBuilder(broker, () => state.toStrategyParams(strategy));
    return () => registerParamsBuilder(broker, null);
  }, [broker, strategy, state, registerParamsBuilder]);

  return (
    <div className="grid grid-cols-12 gap-3 items-start">
      <div className="col-span-3">
        <Label className="text-xs font-mono">{broker}</Label>
      </div>
      <div className="col-span-3">
        <Select
          value={strategy || '__none__'}
          onValueChange={(v) => onStrategyChange(v === '__none__' ? '' : v)}
          disabled={disabled}
        >
          <SelectTrigger className="h-8 text-xs"><SelectValue placeholder="Strategy..." /></SelectTrigger>
          <SelectContent>
            <SelectItem value="__none__">(none / DMA)</SelectItem>
            {strategies.map(s => <SelectItem key={s} value={s}>{s}</SelectItem>)}
          </SelectContent>
        </Select>
      </div>
      <div className="col-span-6">
        {strategy ? (
          <BrokerStrategyFields
            fields={state.fields}
            setFields={state.setFields}
            isLoading={state.isLoading}
            title=""
            hideWhenEmpty
          />
        ) : (
          <div className="text-[11px] text-muted-foreground italic">No strategy selected — routes will be sent without strategy params.</div>
        )}
      </div>
    </div>
  );
}
