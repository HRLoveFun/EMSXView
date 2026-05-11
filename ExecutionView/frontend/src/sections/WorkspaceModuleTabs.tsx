import type { ReactNode } from 'react';
import type { AppModule } from '../hooks/use-app-shell-state';
import { useHandoffContracts } from '../hooks/use-handoff-contracts';

// Hover-prefetch helpers — trigger the dynamic import early so that clicking
// the tab does not block on the first network round-trip. Each import() is
// idempotent: Vite / the browser will cache the chunk after the first call.
const prefetchMarketView = () => {
  void import('../modules/marketview/MarketViewModule');
};
const prefetchCostView = () => {
  void import('../modules/costview/CostViewModule');
};
const prefetchDatabaseView = () => {
  void import('../modules/databaseview/DatabaseViewModule');
};

interface WorkspaceModuleTabsProps {
  activeModule: AppModule;
  onModuleChange: (module: AppModule) => void;
  marketView: ReactNode;
  executionView: ReactNode;
  costView: ReactNode;
  databaseView: ReactNode;
}

export function WorkspaceModuleTabs({
  activeModule,
  onModuleChange,
  marketView,
  executionView,
  costView,
  databaseView,
}: WorkspaceModuleTabsProps) {
  const { activeCandidateHandoff, recommendations } = useHandoffContracts();
  const candidateCount = activeCandidateHandoff?.candidate_payload.row_count ?? 0;
  const recCount = recommendations.length;
  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Workspace module switcher" className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-1.5">
        <button
          role="tab"
          aria-selected={activeModule === 'marketview'}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'marketview'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('marketview')}
          onMouseEnter={prefetchMarketView}
          onFocus={prefetchMarketView}
        >
          Market View
        </button>
        <button
          role="tab"
          aria-selected={activeModule === 'execution'}
          className={`relative rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'execution'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('execution')}
          title={
            candidateCount > 0
              ? `Pending: ${candidateCount} candidate symbol${candidateCount === 1 ? '' : 's'} from Market View, ${recCount} recommendation${recCount === 1 ? '' : 's'} from Cost View`
              : undefined
          }
        >
          Execution View
          {/* Spell out the badge meaning instead of using "MV→EV" jargon
              that non-technical users could not parse on first sight. */}
          {candidateCount > 0 && (
            <span
              className="ml-2 inline-flex items-center rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-semibold text-black"
              aria-label={`${candidateCount} pending candidate${candidateCount === 1 ? '' : 's'} (from Market View)`}
              title={`${candidateCount} pending candidate${candidateCount === 1 ? '' : 's'} (from Market View)`}
            >
              Candidates {candidateCount}
            </span>
          )}
          {recCount > 0 && (
            <span
              className="ml-1 inline-flex items-center rounded-full bg-emerald-500 px-1.5 py-0.5 text-[10px] font-semibold text-black"
              aria-label={`${recCount} pending recommendation${recCount === 1 ? '' : 's'} (from Cost View)`}
              title={`${recCount} pending recommendation${recCount === 1 ? '' : 's'} (from Cost View)`}
            >
              Recommendations {recCount}
            </span>
          )}
        </button>
        <button
          role="tab"
          aria-selected={activeModule === 'costview'}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'costview'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('costview')}
          onMouseEnter={prefetchCostView}
          onFocus={prefetchCostView}
        >
          Cost View
        </button>
        <button
          role="tab"
          aria-selected={activeModule === 'database'}
          className={`rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
            activeModule === 'database'
              ? 'bg-primary text-primary-foreground'
              : 'text-muted-foreground hover:bg-muted hover:text-foreground'
          }`}
          onClick={() => onModuleChange('database')}
          onMouseEnter={prefetchDatabaseView}
          onFocus={prefetchDatabaseView}
        >
          Database
        </button>
      </div>

      {activeModule === 'marketview'
        ? marketView
        : activeModule === 'execution'
          ? executionView
          : activeModule === 'costview'
            ? costView
            : databaseView}
    </div>
  );
}