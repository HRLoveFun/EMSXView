import type { ReactNode } from 'react';
import type { ExecutionViewTab } from '../hooks/use-app-shell-state';

interface ExecutionViewTabsProps {
  activeTab: ExecutionViewTab;
  onTabChange: (tab: ExecutionViewTab) => void;
  monitorView: ReactNode;
  executionView: ReactNode;
  settingsView: ReactNode;
  monitorExceptionCount?: number;
  tradeExceptionCount?: number;
}

export function ExecutionViewTabs({
  activeTab,
  onTabChange,
  monitorView,
  executionView,
  settingsView,
  monitorExceptionCount = 0,
  tradeExceptionCount = 0,
}: ExecutionViewTabsProps) {
  const renderBadge = (count: number) =>
    count > 0 ? (
      <span className="ml-1.5 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold leading-none">
        {count > 99 ? '99+' : count}
      </span>
    ) : null;

  return (
    <>
      <div className="flex items-center gap-1 border-b border-border">
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'monitor'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('monitor')}
        >
          Monitor{renderBadge(monitorExceptionCount)}
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'trade'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('trade')}
        >
          Trade{renderBadge(tradeExceptionCount)}
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'settings'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('settings')}
        >
          Settings
        </button>
      </div>

      {activeTab === 'monitor'
        ? monitorView
        : activeTab === 'trade'
          ? executionView
          : settingsView}
    </>
  );
}
