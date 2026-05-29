import { BrokerStrategyParamsEditor } from './broker-strategy-params-editor';
import type { BrokerStrategySectionProps } from './types';
import { defaultStrategyFor } from './utils';

export function BrokerStrategySection({
  selectedBrokers,
  brokerStrategies,
  strategiesFor,
  setBrokerStrategy,
  registerParamsBuilder,
  registerFieldSetter,
  paramsCacheRef,
  cacheKey,
  editable,
}: BrokerStrategySectionProps) {
  if (selectedBrokers.length === 0) return null;

  const handleResetDefaults = () => {
    for (const b of selectedBrokers) {
      const def = defaultStrategyFor(strategiesFor(b), b);
      setBrokerStrategy(b, def);
    }
  };

  return (
    <div className="border border-border rounded p-3 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-muted-foreground">
          Strategy &amp; parameters per broker
        </div>
        <button
          type="button"
          onClick={handleResetDefaults}
          className="text-[11px] text-primary hover:underline"
          disabled={!editable}
          title="Reset every selected broker to its default strategy and clear unsaved parameter edits"
        >
          Reset to defaults
        </button>
      </div>
      {selectedBrokers.map(b => (
        <BrokerStrategyParamsEditor
          key={b}
          broker={b}
          strategy={brokerStrategies[b] || ''}
          strategies={strategiesFor(b)}
          onStrategyChange={(s) => setBrokerStrategy(b, s)}
          registerParamsBuilder={registerParamsBuilder}
          getCachedSnapshot={(br, st) => paramsCacheRef.current.get(cacheKey(br, st)) as ReturnType<typeof import('@execution/components/broker-strategy-fields').useStrategyFields>['toStrategyParams'] | undefined}
          registerFieldSetter={registerFieldSetter}
          disabled={!editable}
        />
      ))}
    </div>
  );
}
