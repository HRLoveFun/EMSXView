import { useCallback } from 'react';
import type { ModuleId } from '@shared/lib/module-registry';
import { moduleRegistry } from '@shared/lib/module-registry';
import { useHandoffContracts } from '@shared/hooks/use-handoff-contracts';

interface ModuleTabView {
  moduleId: ModuleId;
  content: React.ReactNode;
}

interface WorkspaceModuleTabsProps {
  activeModule: ModuleId;
  onModuleChange: (module: ModuleId) => void;
  /** Map from module id to its rendered content ReactNode. */
  moduleViews: ModuleTabView[];
}

/** Handoff badge shown on the Execution View tab when pending candidates or recommendations exist. */
function HandoffBadge({
  candidateCount,
  recCount,
  hasScaffoldRecs,
}: {
  candidateCount: number;
  recCount: number;
  /** 是否存在骨架模块（Scaffold）来源的推荐 — 提示数据成熟度，仅供参考 */
  hasScaffoldRecs: boolean;
}) {
  const recTitle = `${recCount} pending recommendation${recCount === 1 ? '' : 's'} (from Cost View)${hasScaffoldRecs ? ' — 含骨架模块来源数据，仅供参考' : ''}`;
  return (
    <>
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
          className={`ml-1 inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-semibold text-black ${
            hasScaffoldRecs ? 'bg-amber-500' : 'bg-emerald-500'
          }`}
          aria-label={recTitle}
          title={recTitle}
        >
          Recommendations {recCount}
        </span>
      )}
    </>
  );
}

export function WorkspaceModuleTabs({
  activeModule,
  onModuleChange,
  moduleViews,
}: WorkspaceModuleTabsProps) {
  const { activeCandidateHandoff, recommendations } = useHandoffContracts();
  const candidateCount = activeCandidateHandoff?.candidate_payload.row_count ?? 0;
  const recCount = recommendations.length;
  // P3 整改：Scaffold 来源（如 MarketView 骨架期写入）的推荐不得静默当作
  // GA 结论消费 — 徽标转警示色并在 title/aria 中显式标注
  const hasScaffoldRecs = recommendations.some(
    (rec) => rec.metadata.source_maturity === 'Scaffold',
  );

  const modules = moduleRegistry.getAll();

  const viewMap = new Map(moduleViews.map(v => [v.moduleId, v.content]));

  const handlePrefetch = useCallback((id: ModuleId) => {
    const m = moduleRegistry.get(id);
    m?.prefetch?.();
  }, []);

  return (
    <div className="space-y-4">
      <div role="tablist" aria-label="Workspace module switcher" className="flex flex-wrap items-center gap-2 rounded-xl border bg-card p-1.5">
        {modules.map(m => {
          const isActive = activeModule === m.id;
          // P1-B4: Use declarative showHandoffBadge flag instead of hardcoded
          // module ID check (previously: m.id === 'execution').
          const hasPending = m.showHandoffBadge && (candidateCount > 0 || recCount > 0);

          return (
            <button
              key={m.id}
              role="tab"
              aria-selected={isActive}
              className={`${m.showHandoffBadge ? 'relative' : ''} rounded-lg px-4 py-2 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:bg-muted hover:text-foreground'
              }`}
              onClick={() => onModuleChange(m.id)}
              onMouseEnter={() => handlePrefetch(m.id)}
              onFocus={() => handlePrefetch(m.id)}
              title={
                hasPending
                  ? `Pending: ${candidateCount} candidate symbol${candidateCount === 1 ? '' : 's'} from Market View, ${recCount} recommendation${recCount === 1 ? '' : 's'} from Cost View`
                  : undefined
              }
            >
              {m.label}
              {hasPending && (
                <HandoffBadge
                  candidateCount={candidateCount}
                  recCount={recCount}
                  hasScaffoldRecs={hasScaffoldRecs}
                />
              )}
            </button>
          );
        })}
      </div>

      {modules.map(m => (
        activeModule === m.id && (
          <div key={m.id}>
            {viewMap.get(m.id)}
          </div>
        )
      ))}
    </div>
  );
}
