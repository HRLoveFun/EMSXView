export interface MarketSnapshotRow {
  equ_ticker: string;
  trade_date: string;
  daily_close: number | null;
  daily_volatility: number | null;
  intraday_volatility: number | null;
  total_volume: number | null;
  adv_5d: number | null;
  adv_20d: number | null;
}

export interface MarketSnapshotPayload {
  trade_date: string | null;
  row_count: number;
  rows: MarketSnapshotRow[];
}