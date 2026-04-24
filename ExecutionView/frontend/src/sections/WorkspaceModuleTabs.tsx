import type { ReactNode } from 'react';
import type { AppModule } from '../hooks/use-app-shell-state';
import { useHandoffContracts } from '../hooks/use-handoff-contracts';

interface WorkspaceModuleTabsProps {
  activeModule: AppModule;
  onModuleChange: (module: AppModule) => void;
  marketView: ReactNode;
  executionView: ReactNode;
  costView: ReactNode;
}

export function WorkspaceModuleTabs({
  activeModule,
  onModuleChange,
  marketView,
  executionView,
  costView,
}: WorkspaceModuleTabsProps) {
  const { activeCandidateHandoff, recommendations } = useHandoffContracts();
  const candidateCount = activeCandidateHandoff?.candidate_payload.row_count ?? 0;
  const recCount = recommendations.length;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-1.5">
        <button
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'marketview'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('marketview')}
        >
          MarketView
        </button>
        <button
          className={`relative rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'execution'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('execution')}
          title={
            candidateCount > 0
              ? `Pending MarketView handoff: ${candidateCount} candidate(s) + ${recCount} recommendation(s)`
              : undefined
          }
        >
          ExecutionView Workspace
          {candidateCount > 0 && (
            <span className="ml-2 inline-flex items-center rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-semibold text-black">
              MV→EV {candidateCount}
            </span>
          )}
          {recCount > 0 && (
            <span className="ml-1 inline-flex items-center rounded-full bg-emerald-500 px-1.5 py-0.5 text-[10px] font-semibold text-black">
              CV→EV {recCount}
            </span>
          )}
        </button>
        <button
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'costview'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('costview')}
        >
          CostView
        </button>
      </div>

      {activeModule === 'marketview'
        ? marketView
        : activeModule === 'execution'
          ? executionView
          : costView}
    </div>
  );
}