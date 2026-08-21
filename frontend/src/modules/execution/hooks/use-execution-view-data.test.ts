import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useExecutionViewData } from './use-execution-view-data';

const mockData = vi.hoisted(() => {
  const orders = [
    {
      id: 'ORD1', symbol: 'AAPL', side: 'BUY' as const, status: 'WORKING' as const,
      orderType: 'LIMIT' as const, quantity: 1000, filledQuantity: 200,
      remainingQuantity: 800, price: 150, avgPrice: 149.5,
      dollarValueUsd: 150000, pctChange: 2.5, adv5d: 50000,
      isOddLot: false, createdAt: '2024-01-01T10:00:00Z',
      updatedAt: '2024-01-01T10:00:00Z', account: 'ACC1', portfolio: 'PORT1',
      trader: 'TRADER1', exchange: 'US', currency: 'USD', timeInForce: 'DAY' as const,
      percentFilled: 20, stopPrice: null, notes: '', customNote1: '', customNote2: '',
      customNote3: '', customNote4: '', customNote5: '', traderNotes: '',
      execInstruction: '', strategyType: '', strategyStyle: '',
      strategyPartRate: null, strategyStartTime: '', strategyEndTime: '',
      broker: '', fxRate: null, arrivalPrice: null, lastPrice: null,
      dayAvgPrice: null, mktVwap: null, percentRemain: null,
    },
  ];

  const routes = [
    {
      id: 'R1', routeId: 1, sequence: 1, status: 'WORKING', broker: 'GS',
      amount: 500, filled: 100, working: 400, remainBalance: 400,
      avgPrice: 149, limitPrice: 150, stopPrice: null, lastPrice: 149.8,
      lastShares: 100, dayAvgPrice: 149, dayFill: 100, orderType: 'LIMIT',
      tif: 'DAY', handInstruction: '', execInstruction: '', notes: '',
      strategyType: '', strategyStyle: '', strategyPartRate1: null,
      strategyPartRate2: null, strategyStartTime: '', strategyEndTime: '',
      exchangeDestination: '', executeBroker: '', isManualRoute: 0,
      routeRefId: '', currencyPair: '', urgencyLevel: '',
      routeCreateDate: '', routeCreateTime: '', lastFillDate: '',
      lastFillTime: '', timeStamp: '', routeLastUpdateTime: '',
      fillId: 0, percentRemain: null, reasonCode: '', reasonDesc: '',
      brokerStatus: '', settleAmount: null, settleDate: '',
      commRate: null, brokerComm: null, userCommRate: null, userFees: null,
      miscFees: null, userNetMoney: null, principal: null, routePrice: null,
      ticker: 'AAPL', side: 'BUY', portfolio: 'PORT1', trader: 'TRADER1',
      traderUuid: 0, currency: 'USD', exchange: 'US',
    },
  ];

  return { orders, routes };
});

const mockApiService = vi.hoisted(() => ({
  getTraderInfo: vi.fn().mockResolvedValue({ success: true, data: { traderName: 'TEST_TRADER' } }),
  getOrders: vi.fn().mockResolvedValue({ success: true, data: mockData.orders }),
  getRoutes: vi.fn().mockResolvedValue({ success: true, data: mockData.routes }),
  refreshOrders: vi.fn().mockResolvedValue({ success: true, data: mockData.orders }),
  batchUpdate: vi.fn().mockResolvedValue({ success: true, data: { success: true, updatedCount: 2, message: 'ok' } }),
  cancelRoute: vi.fn().mockResolvedValue({ success: true }),
  modifyRoute: vi.fn().mockResolvedValue({ success: true }),
  modifyOrder: vi.fn().mockResolvedValue({ success: true }),
  routeOrder: vi.fn().mockResolvedValue({ success: true, data: { success: true, orderId: 'ORD1', broker: 'GS', quantity: 500 } }),
}));

vi.mock('@execution/services/execution-api', () => ({
  apiService: mockApiService,
}));

const mockCache = vi.hoisted(() => ({
  isValid: vi.fn().mockReturnValue(true),
  get: vi.fn().mockReturnValue(null),
  set: vi.fn(),
  clear: vi.fn(),
}));

vi.mock('@execution/lib', () => ({
  CACHE_CONFIGS: { TRADER_INFO: { ttl: 30000 } },
  createCache: vi.fn(() => mockCache),
  getOrFetch: vi.fn((_cache: unknown, fetchFn: () => unknown) => fetchFn()),
  clearAllCaches: vi.fn(),
  getReconcileIntervalMs: vi.fn(() => 15000),
}));

describe('useExecutionViewData', () => {
  const defaultProps = {
    isAuthenticated: true,
    isBackendReady: true,
    streamConnected: false,
    allowFallbackFetch: false,
    onAuthenticationFailure: vi.fn(),
    onToast: vi.fn(),
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('fetches initial data when authenticated and backend ready', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => {
      expect(result.current.allOrders).toEqual(mockData.orders);
      expect(result.current.allRoutes).toEqual(mockData.routes);
    });

    expect(result.current.currentTrader).toBe('TEST_TRADER');
    expect(result.current.isLoading).toBe(false);
  });

  it('does not fetch when not authenticated', () => {
    renderHook(() => useExecutionViewData({ ...defaultProps, isAuthenticated: false }));

    expect(mockApiService.getOrders).not.toHaveBeenCalled();
    expect(mockApiService.getTraderInfo).not.toHaveBeenCalled();
  });

  it('resets state when authentication is lost', async () => {
    const { rerender, result } = renderHook(
      ({ isAuthenticated }: { isAuthenticated: boolean }) =>
        useExecutionViewData({ ...defaultProps, isAuthenticated }),
      { initialProps: { isAuthenticated: true } },
    );

    await waitFor(() => expect(result.current.allOrders.length).toBe(1));

    rerender({ isAuthenticated: false });

    expect(result.current.allOrders).toEqual([]);
    expect(result.current.allRoutes).toEqual([]);
    expect(result.current.currentTrader).toBe('');
    expect(result.current.isLoading).toBe(false);
  });

  it('handleRefresh fetches fresh data', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => expect(mockApiService.getOrders).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.handleRefresh();
    });

    expect(mockApiService.refreshOrders).toHaveBeenCalledTimes(1);
    expect(result.current.isLoading).toBe(false);
  });

  it('handleBatchUpdate calls batch API and refetches', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => expect(mockApiService.getOrders).toHaveBeenCalledTimes(1));

    await act(async () => {
      await result.current.handleBatchUpdate({
        orderIds: ['ORD1'],
        field: 'price' as const,
        value: '155',
      });
    });

    expect(mockApiService.batchUpdate).toHaveBeenCalledTimes(1);
    expect(defaultProps.onToast).toHaveBeenCalledWith('success', 'ok');
  });

  it('handleCancelRoute sends cancel request', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await act(async () => {
      await result.current.handleCancelRoute({ sequence: 1, routeId: 1 });
    });

    expect(mockApiService.cancelRoute).toHaveBeenCalledWith({ sequence: 1, routeId: 1 });
    expect(defaultProps.onToast).toHaveBeenCalledWith('success', expect.stringContaining('cancel'));
  });

  it('handleSelectionChange updates selected orders', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => expect(mockApiService.getOrders).toHaveBeenCalledTimes(1));

    act(() => {
      result.current.handleSelectionChange(new Set(['ORD1']));
    });

    expect(result.current.selectedOrders).toEqual(new Set(['ORD1']));

    act(() => {
      result.current.handleClearSelection();
    });

    expect(result.current.selectedOrders).toEqual(new Set());
  });

  it('clearCache triggers cache clear and trader refetch', async () => {
    const { result } = renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => expect(mockApiService.getTraderInfo.mock.calls.length).toBeGreaterThanOrEqual(1));

    const callsBeforeClear = mockApiService.getTraderInfo.mock.calls.length;

    await act(async () => {
      await result.current.handleClearCache();
    });

    await waitFor(() => {
      expect(mockApiService.getTraderInfo.mock.calls.length).toBeGreaterThan(callsBeforeClear);
    });
  });

  it('starts polling when stream is disconnected', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });

    renderHook(() => useExecutionViewData(defaultProps));

    await waitFor(() => expect(mockApiService.getOrders).toHaveBeenCalledTimes(1));

    act(() => { vi.advanceTimersByTime(3000); });

    expect(mockApiService.getOrders).toHaveBeenCalledTimes(2);

    vi.useRealTimers();
  });
});
