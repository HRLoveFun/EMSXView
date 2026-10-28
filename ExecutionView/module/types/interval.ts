/**
 * 057 DL-30：执行区间量价序列类型（只读）。
 *
 * 区间边界由订单创建/开始与结束时刻确定；缺 bar 的桶由 `is_gap` 显式标注，
 * 消费方不得插值。
 */

export interface IntervalPoint {
  bucket_start: string;
  bucket_end: string;
  price: number | null;
  vwap: number | null;
  volume: number;
  cum_volume: number;
  is_gap: boolean;
}

export type IntervalSeriesSource = 'intraday' | 'formal' | 'none';

export interface IntervalSeriesPayload {
  equ_ticker: string;
  trade_date: string;
  start: string;
  end: string;
  bucket_minutes: number;
  source: IntervalSeriesSource;
  points: IntervalPoint[];
  interval_vwap: number | null;
  total_volume: number;
  bar_count: number;
  gap_buckets: number;
  generated_at: string;
}

export interface IntervalSeriesRequest {
  equ_ticker: string;
  trade_date: string;
  start: string;
  end: string;
  bucket_minutes?: number;
}
