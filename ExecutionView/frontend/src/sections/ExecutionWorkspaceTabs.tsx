import type { ReactNode } from 'react';
import type { ExecutionWorkspaceTab } from '../hooks/use-app-shell-state';

interface ExecutionWorkspaceTabsProps {
  activeTab: ExecutionWorkspaceTab;
  onTabChange: (tab: ExecutionWorkspaceTab) => void;
  monitorView: ReactNode;
  executionView: ReactNode;
  settingsView: ReactNode;
}

export function ExecutionWorkspaceTabs({
  activeTab,
  onTabChange,
  monitorView,
  executionView,
  settingsView,
}: ExecutionWorkspaceTabsProps) {
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
          Monitor
        </button>
        <button
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'execution'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('execution')}
        >
          ExecutionView
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
        : activeTab === 'execution'
          ? executionView
          : settingsView}
    </>
  );
}