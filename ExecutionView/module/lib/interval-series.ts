/** 057 DL-30：执行区间解析与图表数据整形（纯函数，便于单测）。 */

import type { IntervalPoint, Order } from '@execution/types';

export interface ResolvedInterval {
  tradeDate: string;
  start: string;
  end: string;
  /** 订单未给结束时刻，终点按「当前时刻 / 收盘」近似 */
  endAssumed: boolean;
}

const pad2 = (value: number): string => String(value).padStart(2, '0');

const toHms = (date: Date): string =>
  `${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`;

const dateKey = (date: Date): string =>
  `${date.getFullYear()}${pad2(date.getMonth() + 1)}${pad2(date.getDate())}`;

/** 兼容 "09:30" / "09:30:00" / "093000" / "0930"；非法返回 null。 */
export const normalizeTime = (value: string | null | undefined): string | null => {
  if (!value) return null;
  const text = String(value).trim();
  const colon = /^(\d{1,2}):(\d{2})(?::(\d{2}))?$/.exec(text);
  if (colon) {
    const hour = Number(colon[1]);
    const minute = Number(colon[2]);
    const second = Number(colon[3] ?? 0);
    if (hour > 23 || minute > 59 || second > 59) return null;
    return `${pad2(hour)}:${pad2(minute)}:${pad2(second)}`;
  }
  const digits = /^(\d{2})(\d{2})(\d{2})?$/.exec(text);
  if (!digits) return null;
  const hour = Number(digits[1]);
  const minute = Number(digits[2]);
  const second = Number(digits[3] ?? 0);
  if (hour > 23 || minute > 59 || second > 59) return null;
  return `${pad2(hour)}:${pad2(minute)}:${pad2(second)}`;
};

/** BDIB 复合代码：`AAPL` + `US` → `AAPL US Equity`；已是复合代码则原样。 */
export const resolveEquTicker = (order: Order): string => {
  const symbol = order.symbol.trim();
  if (symbol.includes(' Equity')) return symbol;
  const exchange = (order.exchange || '').trim();
  return exchange ? `${symbol} ${exchange} Equity` : symbol;
};

/**
 * 区间边界：优先订单策略起止；缺结束时刻时按「同日=当前时刻，非同日=16:00」
 * 近似，并以 `endAssumed` 标注，调用方须在界面提示。
 */
export const resolveInterval = (order: Order, now: Date = new Date()): ResolvedInterval => {
  const created = new Date(order.createdAt);
  const base = Number.isNaN(created.getTime()) ? now : created;
  const tradeDate = dateKey(base);
  const start = normalizeTime(order.strategyStartTime) ?? toHms(base);
  const explicitEnd = normalizeTime(order.strategyEndTime);
  const end = explicitEnd ?? (tradeDate === dateKey(now) ? toHms(now) : '16:00:00');
  return { tradeDate, start, end, endAssumed: explicitEnd === null };
};

export interface IntervalChartPoint {
  time: string;
  price: number | null;
  cumVolume: number;
  isGap: boolean;
}

export const toChartData = (points: IntervalPoint[]): IntervalChartPoint[] =>
  points.map((point) => ({
    time: point.bucket_start.slice(0, 5),
    price: point.price,
    cumVolume: point.cum_volume,
    isGap: point.is_gap,
  }));

/**
 * 开发预览用示例订单（仅 `import.meta.env.DEV` 下由 MonitorBoard 提供入口）。
 * 选一个有真实 bar 供给的标的与交易日，便于在设计复核时看到完整图表。
 */
export const buildPreviewOrder = (): Order =>
  ({
    id: 'preview',
    symbol: '601398',
    exchange: 'CH',
    createdAt: '2026-10-26T09:30:00',
    strategyStartTime: '09:30',
    strategyEndTime: '10:30',
    avgPrice: 8.42,
    arrivalPrice: 8.38,
  }) as Order;
