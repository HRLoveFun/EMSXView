import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import ExecutionModule from './ExecutionModule';

/**
 * ExecutionView 模块独立测试 —— 只验证模块编排层（数据获取 → 状态管理 → 渲染 → 事件处理 → 上报）。
 *
 * 模块外依赖全部以桩替换：Shell 宿主服务、启动状态、数据 hook、子视图。
 * 子视图与数据 hook 本身由各自单测覆盖，此处隔离后即可在不启动后端、不挂载 Shell 的前提下
 * 独立验证模块契约（`module.contract.ts`）与四条核心路径。
 */

const shellContext = vi.hoisted(() => ({
  current: {
    navigateTo: vi.fn(),
    addToast: vi.fn(),
    realtimeClient: null,
    streamConnected: false,
    streamEverConnected: false,
    subscriptionsWarming: false,
    subscriptionsWarmingMode: 'initial',
    logout: vi.fn(),
  },
}));

vi.mock('@shared/lib/shell-context', () => ({
  useShellContext: () => shellContext.current,
}));

const startupStatus = vi.hoisted(() => ({ current: { elapsedSeconds: 0, isReady: true } }));

vi.mock('@shared/hooks/use-startup-status', () => ({
  useStartupStatus: () => startupStatus.current,
}));

const executionViewData = vi.hoisted(() => ({
  allOrders: [] as unknown[],
  allRoutes: [] as unknown[],
  currentTrader: '',
  selectedOrders: new Set<string>(),
  isLoading: false,
  fetchOrders: vi.fn(),
  handleRefresh: vi.fn(),
  handleBatchUpdate: vi.fn(),
  handleSelectionChange: vi.fn(),
  handleClearSelection: vi.fn(),
  handleClearCache: vi.fn(),
  handleCancelRoute: vi.fn(),
  handleModifyRoute: vi.fn(),
  handleModifyOrder: vi.fn(),
}));

vi.mock('@execution/hooks/use-execution-view-data', () => ({
  useExecutionViewData: () => executionViewData,
}));

const streamState = vi.hoisted(() => ({ orders: [] as unknown[], routes: [] as unknown[] }));

vi.mock('@execution/hooks/use-orders-stream', () => ({
  useOrdersStream: () => ({ orders: streamState.orders }),
}));

vi.mock('@execution/hooks/use-routes-stream', () => ({
  useRoutesStream: () => ({ routes: streamState.routes }),
}));

// 条件判定置为恒真，使 monitorCount 可直接由订单数推导（隔离条件算法本身）
vi.mock('@execution/lib/monitor-conditions', () => ({
  loadConditions: () => ({}),
  saveConditions: vi.fn(),
  matchesAnyCondition: () => true,
}));

const monitorBoard = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => null));
const executionBoard = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => null));
const subOrderReviewPanel = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => null));
const settingsBoard = vi.hoisted(() => vi.fn((_props: Record<string, unknown>) => null));

vi.mock('@execution/views/MonitorBoard', () => ({ MonitorBoard: monitorBoard }));
vi.mock('@execution/views/ExecutionBoard', () => ({ ExecutionBoard: executionBoard }));
vi.mock('@execution/components/sub-order-review-panel', () => ({ SubOrderReviewPanel: subOrderReviewPanel }));
vi.mock('@execution/views/settings/SettingsBoard', () => ({ SettingsBoard: settingsBoard }));

/** 取子视图最后一次渲染时收到的 props。 */
const lastProps = (view: typeof monitorBoard): Record<string, unknown> =>
  view.mock.calls.at(-1)?.[0] ?? {};

/** 重置 Shell 宿主桩到默认态。 */
const resetShellContext = (): void => {
  shellContext.current = {
    navigateTo: vi.fn(),
    addToast: vi.fn(),
    realtimeClient: null,
    streamConnected: false,
    streamEverConnected: false,
    subscriptionsWarming: false,
    subscriptionsWarmingMode: 'initial',
    logout: vi.fn(),
  };
};

describe('ExecutionModule', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetShellContext();
    startupStatus.current = { elapsedSeconds: 0, isReady: true };
    executionViewData.allOrders = [{ id: 'ORD1' }, { id: 'ORD2' }];
    executionViewData.allRoutes = [{ id: 'R1' }];
    streamState.orders = [];
    streamState.routes = [];
  });

  it('默认激活 Monitor 页签，并把订单/路由数据透传给视图', async () => {
    render(<ExecutionModule onContribute={vi.fn()} />);

    expect(screen.getByRole('tab', { name: /Monitor/ })).toHaveAttribute('aria-selected', 'true');

    await waitFor(() => expect(monitorBoard).toHaveBeenCalled());
    expect(lastProps(monitorBoard).allOrders).toEqual(executionViewData.allOrders);
    expect(lastProps(monitorBoard).allRoutes).toEqual(executionViewData.allRoutes);
    expect(lastProps(monitorBoard).isLoading).toBe(false);
  });

  it('页签切换后渲染对应视图', async () => {
    render(<ExecutionModule onContribute={vi.fn()} />);

    fireEvent.click(screen.getByRole('tab', { name: /^Trade$/ }));
    await waitFor(() => expect(executionBoard).toHaveBeenCalled());
    expect(lastProps(executionBoard).orders).toEqual(executionViewData.allOrders);
    expect(lastProps(executionBoard).routes).toEqual(executionViewData.allRoutes);

    fireEvent.click(screen.getByRole('tab', { name: /^Route Engine$/ }));
    await waitFor(() => expect(subOrderReviewPanel).toHaveBeenCalled());

    fireEvent.click(screen.getByRole('tab', { name: /^Settings$/ }));
    await waitFor(() => expect(settingsBoard).toHaveBeenCalled());
  });

  it('按模块契约向 Shell 上报贡献信息', async () => {
    const onContribute = vi.fn();
    render(<ExecutionModule onContribute={onContribute} />);

    await waitFor(() => expect(onContribute).toHaveBeenCalled());

    const contribution = onContribute.mock.calls.at(-1)![0];
    expect(contribution.counts).toEqual({ orders: 2, routes: 1 });
    expect(contribution.isLoading).toBe(false);
    expect(contribution.lastUpdatedAt).toEqual(expect.any(Number));
    expect(contribution.refresh).toBe(executionViewData.handleRefresh);
    expect(contribution.clearCache).toBe(executionViewData.handleClearCache);
  });

  it('实时流已连接且有数据时优先采用流数据', async () => {
    const onContribute = vi.fn();
    shellContext.current = { ...shellContext.current, streamConnected: true };
    streamState.orders = [{ id: 'STREAM-1' }];
    streamState.routes = [{ id: 'SR1' }, { id: 'SR2' }];

    render(<ExecutionModule onContribute={onContribute} />);

    await waitFor(() => expect(onContribute).toHaveBeenCalled());
    expect(onContribute.mock.calls.at(-1)![0].counts).toEqual({ orders: 1, routes: 2 });
    expect(lastProps(monitorBoard).allOrders).toEqual([{ id: 'STREAM-1' }]);
  });

  it('订阅预热期按模式渲染降级提示', () => {
    const onContribute = vi.fn();
    const { rerender } = render(<ExecutionModule onContribute={onContribute} />);
    expect(screen.queryByText(/Establishing EMSX subscriptions/)).toBeNull();

    shellContext.current = {
      ...shellContext.current,
      subscriptionsWarming: true,
      subscriptionsWarmingMode: 'initial',
    };
    rerender(<ExecutionModule onContribute={onContribute} />);
    expect(screen.getByText(/Establishing EMSX subscriptions/)).toBeInTheDocument();

    shellContext.current = { ...shellContext.current, subscriptionsWarmingMode: 'reconnecting' };
    rerender(<ExecutionModule onContribute={onContribute} />);
    expect(screen.getByText(/Realtime stream interrupted/)).toBeInTheDocument();

    startupStatus.current = { elapsedSeconds: 120, isReady: false };
    shellContext.current = { ...shellContext.current, subscriptionsWarmingMode: 'timed-out' };
    rerender(<ExecutionModule onContribute={onContribute} />);
    expect(screen.getByText(/taking longer than expected \(120s\)/)).toBeInTheDocument();
  });
});
