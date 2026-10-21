import { FileSpreadsheet } from 'lucide-react';

import { useAsyncData } from '@shared/hooks/use-async-data';
import { fetchPreTradeOrders } from '../services/api';
import type { ExportOrderRow, PreTradeOrdersPayload } from '../types';
import { fmtCompact, fmtPercent, getIntentLabel, getIntentTone, getUnmatchedReasonText } from '../marketview-utils';

// 单行意图徽标：MIX 附带收盘比例，UNMAPPED 红底提示人工补登
const IntentBadge = ({ row }: { row: ExportOrderRow }) => (
  <span
    className={`inline-flex rounded-full border px-2 py-1 text-[11px] font-medium ${getIntentTone(row.intent.benchmark)}`}
    title={row.intent.raw_note || 'No PM note'}
  >
    {getIntentLabel(row.intent.benchmark, row.intent.close_pct)}
  </span>
);

// 导出元信息条：文件名、导出时间、订单数、意图覆盖率、未匹配数、映射版本
const ExportMetaBar = ({ payload }: { payload: PreTradeOrdersPayload }) => (
  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
    <div className="inline-flex items-center gap-1 rounded-full border border-border px-3 py-1">
      <FileSpreadsheet className="h-3.5 w-3.5" />
      {payload.export_file_name || 'No export file'}
    </div>
    <div className="rounded-full border border-border px-3 py-1">
      Exported {payload.exported_at ? new Date(payload.exported_at).toLocaleString() : 'N/A'}
    </div>
    <div className="rounded-full border border-border px-3 py-1">{payload.order_count} orders</div>
    <div className="rounded-full border border-border px-3 py-1">
      Intent coverage {fmtPercent(payload.intent_coverage_pct)}
    </div>
    <div className="rounded-full border border-border px-3 py-1">
      {payload.unmatched.length} unmatched
    </div>
    <div className="rounded-full border border-border px-3 py-1">Mapping {payload.intent_mapping_version}</div>
  </div>
);

// 未匹配清单：意图不可映射或缺连接键的订单，人工补登入口
const UnmatchedList = ({ payload }: { payload: PreTradeOrdersPayload }) => {
  if (!payload.unmatched.length) {
    return null;
  }
  return (
    <div className="rounded-xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm">
      <p className="font-medium text-amber-700">Unmatched intents (manual follow-up)</p>
      <ul className="mt-2 space-y-1 text-muted-foreground">
        {payload.unmatched.map((entry) => (
          <li key={`${entry.code}-${entry.pm_note}`}>
            {entry.code}: {getUnmatchedReasonText(entry.reason)}
          </li>
        ))}
      </ul>
    </div>
  );
};

const OrderRow = ({ row }: { row: ExportOrderRow }) => (
  <tr className="border-t border-border/60">
    <td className="px-3 py-2 font-medium text-foreground">{row.code}</td>
    <td className="px-3 py-2 text-muted-foreground">{row.name}</td>
    <td className="px-3 py-2">{row.side}</td>
    <td className="px-3 py-2 text-right">{fmtCompact(row.qty)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.pct_filled)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.q_pct_5d_adv)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.q_pct_tdy)}</td>
    <td className="px-3 py-2 text-right">{fmtPercent(row.rem_bal_pct_avg_cls_auct_vol)}</td>
    <td className="px-3 py-2">{row.status}</td>
    <td className="px-3 py-2 text-muted-foreground">{row.brkr_code}</td>
    <td className="px-3 py-2">
      <IntentBadge row={row} />
    </td>
  </tr>
);

// EMSX 导出盘前单 v0（057 DL-01）：只读展示导出现成字段与 PM 意图，
// 不做任何计算；数据随收件箱最新导出刷新（DL-07 后改读盘中库）。
export const ExportOrdersPanel = () => {
  const { data, error, isLoading } = useAsyncData<PreTradeOrdersPayload>(
    'pre-trade-orders',
    fetchPreTradeOrders,
  );

  return (
    <section className="space-y-4 rounded-2xl border bg-card p-6 shadow-sm">
      <div>
        <p className="text-sm font-medium text-foreground">EMSX export pre-trade orders</p>
        <p className="mt-1 text-sm text-muted-foreground">
          Parsed from the latest manual EMSX order export (PM Note 13 intents). Read-only: values are shown
          as exported, with no derivation. Configure <code>EMSXVIEW_EXPORT_INBOX_DIR</code> on the
          MarketView service to populate this panel.
        </p>
      </div>

      {isLoading ? (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          Loading EMSX export...
        </div>
      ) : error ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-700">
          {error.message}
        </div>
      ) : data && data.order_count > 0 ? (
        <>
          <ExportMetaBar payload={data} />
          <div className="overflow-x-auto rounded-xl border border-border">
            <table className="w-full min-w-[1080px] text-sm">
              <thead className="bg-muted/50 text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-3 py-3 text-left font-medium">Code</th>
                  <th className="px-3 py-3 text-left font-medium">Name</th>
                  <th className="px-3 py-3 text-left font-medium">Side</th>
                  <th className="px-3 py-3 text-right font-medium">Qty</th>
                  <th className="px-3 py-3 text-right font-medium">Filled %</th>
                  <th className="px-3 py-3 text-right font-medium">Q% 5D ADV</th>
                  <th className="px-3 py-3 text-right font-medium">Q % tdy</th>
                  <th className="px-3 py-3 text-right font-medium">Rem Bal % Cls Auct</th>
                  <th className="px-3 py-3 text-left font-medium">Status</th>
                  <th className="px-3 py-3 text-left font-medium">Brkr</th>
                  <th className="px-3 py-3 text-left font-medium">Intent</th>
                </tr>
              </thead>
              <tbody>
                {data.orders.map((row) => (
                  <OrderRow key={`${row.code}-${row.intent.order_key || row.pm_note}`} row={row} />
                ))}
              </tbody>
            </table>
          </div>
          <UnmatchedList payload={data} />
        </>
      ) : (
        <div className="rounded-xl border border-dashed border-border p-6 text-sm text-muted-foreground">
          No EMSX export available. Ask the trader to export the order blotter to the configured inbox.
        </div>
      )}
    </section>
  );
};
