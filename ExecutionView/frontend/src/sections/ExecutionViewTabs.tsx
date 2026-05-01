import type { ReactNode } from 'react';
import type { ExecutionViewTab } from '../hooks/use-app-shell-state';

interface ExecutionViewTabsProps {
  activeTab: ExecutionViewTab;
  onTabChange: (tab: ExecutionViewTab) => void;
  monitorView: ReactNode;
  executionView: ReactNode;
  routeEngineView: ReactNode;
  settingsView: ReactNode;
  monitorExceptionCount?: number;
  tradeExceptionCount?: number;
}

export function ExecutionViewTabs({
  activeTab,
  onTabChange,
  monitorView,
  executionView,
  routeEngineView,
  settingsView,
  monitorExceptionCount = 0,
  tradeExceptionCount = 0,
}: ExecutionViewTabsProps) {
  // The badge represents the count of orders currently matching alert
  // conditions. We surface this as a tooltip + aria-label so non-technical
  // users (and screen readers) understand the meaning of the red number,
  // instead of having to guess from a bare digit floating beside the tab.
  const renderBadge = (count: number, kind: 'monitor' | 'trade') => {
    if (count <= 0) return null;
    const label =
      kind === 'monitor'
        ? `${count} 个订单触发了告警条件`
        : `${count} 个订单存在交易异常`;
    return (
      <span
        className="ml-1.5 inline-flex items-center justify-center min-w-[16px] h-4 px-1 rounded-full bg-red-500 text-white text-[10px] font-semibold leading-none"
        title={label}
        aria-label={label}
      >
        {count > 99 ? '99+' : count}
      </span>
    );
  };

  return (
    <>
      <div role="tablist" aria-label="ExecutionView 子标签" className="flex items-center gap-1 border-b border-border">
        <button
          role="tab"
          aria-selected={activeTab === 'monitor'}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'monitor'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('monitor')}
        >
          监控{renderBadge(monitorExceptionCount, 'monitor')}
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'trade'}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'trade'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('trade')}
        >
          交易{renderBadge(tradeExceptionCount, 'trade')}
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'route-engine'}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'route-engine'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('route-engine')}
        >
          路由引擎
        </button>
        <button
          role="tab"
          aria-selected={activeTab === 'settings'}
          className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px ${
            activeTab === 'settings'
              ? 'border-primary text-primary'
              : 'border-transparent text-muted-foreground hover:text-foreground'
          }`}
          onClick={() => onTabChange('settings')}
        >
          设置
        </button>
      </div>

      {activeTab === 'monitor'
        ? monitorView
        : activeTab === 'trade'
          ? executionView
          : activeTab === 'route-engine'
            ? routeEngineView
            : settingsView}
    </>
  );
}
