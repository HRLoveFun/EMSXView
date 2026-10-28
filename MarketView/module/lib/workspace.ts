import type {
  LiveMarketStateStatus,
  LiveQuotes,
  MarketAlertSeverity,
  MarketCandidatePayload,
  MarketSnapshotPayload,
  MarketSnapshotRow,
  MarketStateSnapshot,
} from '../types';

// 后端 trade_date 约定为 YYYYMMDD；HTML date input 约定为 YYYY-MM-DD。
// 以下两个函数负责双向转换，非法输入一律降级为空值。

export function buildMarketCandidatePayload(
  snapshot: MarketSnapshotPayload,
  selectedTickers: string[],
): MarketCandidatePayload {
  if (!selectedTickers.length) {
    return snapshot.candidate_payload;
  }

  const selected = new Set(selectedTickers);
  const candidates = snapshot.candidate_payload.candidates.filter((candidate) => selected.has(candidate.equ_ticker));

  return {
    ...snapshot.candidate_payload,
    row_count: candidates.length,
    candidates,
  };
}

/**
 * 把实时快照转成表格索引（按 equ_ticker）。
 *
 * `enabled=false`（后端开关关闭或无行情）时返回空索引，表格列回落为占位符，
 * 不把「无数据」渲染成 0。
 */
export function buildLiveQuotes(
  snapshot: MarketStateSnapshot | null,
  status: LiveMarketStateStatus,
): LiveQuotes {
  const enabled = snapshot?.enabled ?? false;
  const rows = enabled ? snapshot?.tickers ?? [] : [];
  return {
    byTicker: new Map(rows.map((state) => [state.equ_ticker, state])),
    status,
    enabled,
    asOf: snapshot?.as_of ?? null,
  };
}

/** 实时涨跌幅文本：带符号；缺失返回破折号。 */
export function fmtSignedPercent(value: number | null | undefined, digits = 2): string {
  if (value == null) return '—';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  })}%`;
}

/** 涨跌方向着色（涨绿跌红，与池板 Bid/Ask 配色一致）。 */
export function pctToneClass(value: number | null | undefined): string {
  if (value == null || value === 0) return 'text-muted-foreground';
  return value > 0 ? 'text-emerald-500' : 'text-rose-500';
}

/**
 * 盘中实时参与率：实时成交量 ÷ 日度 ADV（%）。
 *
 * 用日度快照的 ADV20 做分母而不是订阅 5 日均量：mktdata 的 VOLUME_AVG_5D
 * 在本机终端不推送（2026-10-28 实测），而 ADV20 已在池板载荷里。
 */
export function liveVolumeVsAdvPct(
  volume: number | null | undefined,
  adv: number | null | undefined,
): number | null {
  if (volume == null || adv == null || adv <= 0) return null;
  return (volume / adv) * 100;
}

export function countRowsWithSeverity(
  rows: MarketSnapshotRow[],
  severity: Extract<MarketAlertSeverity, 'warning' | 'critical'>,
): number {
  return rows.filter(
    (row) => row.liquidity_alert === severity || row.volatility_alert === severity,
  ).length;
}

// 将后端 YYYYMMDD 日期转换为 date input 可用的 YYYY-MM-DD
export function toISODateInput(value: string | undefined | null): string {
  if (!value || !/^\d{8}$/.test(value)) {
    return '';
  }
  return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

// 将 date input 的 YYYY-MM-DD 转换为后端 YYYYMMDD；空串返回 undefined 以清除筛选
export function fromISODateInput(value: string): string | undefined {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) {
    return undefined;
  }
  return value.replaceAll('-', '');
}