/**
 * Shared constants for table grouping, status options, and order-type options.
 * Used by OrderTable, MonitorBoard, and (partially) RouteTable.
 */
import type { OrderStatus, OrderType as OType } from '@/types';

// ─── Order GROUP BY ─────────────────────────────────────────────────────────

export const ORDER_GROUP_BY_OPTIONS = [
  { value: 'none',      label: 'No Grouping' },
  { value: 'symbol',    label: 'Ticker'      },
  { value: 'side',      label: 'Side'        },
  { value: 'status',    label: 'Status'      },
  { value: 'portfolio', label: 'Portfolio'   },
  { value: 'trader',    label: 'Trader'      },
  { value: 'exchange',  label: 'Exchange'    },
  { value: 'currency',  label: 'Currency'    },
] as const;

export type OrderGroupByValue = (typeof ORDER_GROUP_BY_OPTIONS)[number]['value'];

export const ORDER_GROUP_BY_LABELS: Record<OrderGroupByValue, string> = {
  none: '', symbol: 'Ticker', side: 'Side', status: 'Status',
  portfolio: 'Portfolio', trader: 'Trader', exchange: 'Exchange', currency: 'Currency',
};

// ─── Route GROUP BY ─────────────────────────────────────────────────────────

export const ROUTE_GROUP_BY_OPTIONS = [
  { value: 'none',      label: 'No Grouping' },
  { value: 'exchange',  label: 'Exchange'    },
  { value: 'ticker',    label: 'Ticker'      },
  { value: 'side',      label: 'Side'        },
  { value: 'status',    label: 'Status'      },
  { value: 'broker',    label: 'Broker'      },
  { value: 'portfolio', label: 'Portfolio'   },
  { value: 'trader',    label: 'Trader'      },
] as const;

export type RouteGroupByValue = (typeof ROUTE_GROUP_BY_OPTIONS)[number]['value'];

export const ROUTE_GROUP_BY_LABELS: Record<RouteGroupByValue, string> = {
  none: '', exchange: 'Exchange', ticker: 'Ticker', side: 'Side', status: 'Status',
  broker: 'Broker', portfolio: 'Portfolio', trader: 'Trader',
};

// ─── Status and order-type option lists ─────────────────────────────────────

export const STATUS_OPTIONS: { value: OrderStatus; label: string }[] = [
  { value: 'NEW',            label: 'New'            },
  { value: 'ASSIGN',         label: 'Assign'         },
  { value: 'WORKING',        label: 'Working'        },
  { value: 'PARTIAL',        label: 'Partial'        },
  { value: 'FILLED',         label: 'Filled'         },
  { value: 'CANCELLED',      label: 'Cancelled'      },
  { value: 'COMPLETED',      label: 'Completed'      },
  { value: 'QUEUED',         label: 'Queued'         },
  { value: 'SUSPENDED',      label: 'Suspended'      },
  { value: 'PENDING_CANCEL', label: 'Pending Cancel' },
  { value: 'REJECTED',       label: 'Rejected'       },
];

export const ORDER_TYPE_OPTIONS: { value: OType; label: string }[] = [
  { value: 'LIMIT',      label: 'Limit'      },
  { value: 'MARKET',     label: 'Market'     },
  { value: 'STOP',       label: 'Stop'       },
  { value: 'STOP_LIMIT', label: 'Stop Limit' },
];

export const ROUTE_STATUS_OPTIONS = [
  'SENT', 'WORKING', 'PARTFILL', 'FILLED', 'CANCEL',
  'CXLREQ', 'CXLREJ', 'CXLREP', 'CXLRPRQ', 'CXLRPRJ',
  'REJECTED', 'DONE', 'QUEUED', 'HOLD', 'BUST',
  'CORRECTED', 'REPPEN', 'ROUTE-ERR', 'OMS-PEND',
  'A-SENT', 'ALLOCATED', 'OA-SENT',
] as const;
