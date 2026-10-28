/** 057 DL-30：执行区间量价 API（只读）。 */

import type { IntervalSeriesPayload, IntervalSeriesRequest } from '@execution/types';
import { apiFetch } from './http-client';

export const intervalApi = {
  async getIntervalSeries(request: IntervalSeriesRequest): Promise<IntervalSeriesPayload> {
    const params = new URLSearchParams({
      equ_ticker: request.equ_ticker,
      trade_date: request.trade_date,
      start: request.start,
      end: request.end,
      bucket_minutes: String(request.bucket_minutes ?? 5),
    });
    const response = await apiFetch<IntervalSeriesPayload>(
      `/api/execution/interval-series?${params.toString()}`,
    );
    if (!response.success || !response.data) {
      throw new Error(response.error ?? 'Interval series unavailable');
    }
    return response.data;
  },
};
