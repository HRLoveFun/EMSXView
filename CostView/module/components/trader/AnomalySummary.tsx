import { AlertOctagon, ArrowRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import type { TraderAnomalySummary } from '../../types';

/** 按规则列表展示条数（方案 §4.11：Top 5） */
const RULE_TOP_N = 5;

interface AnomalySummaryProps {
  summary: TraderAnomalySummary;
  /** 点击异常订单 → 选中详情（缺省时列表只读） */
  onSelectOrder?: (orderId: string, orderAsOfDate: string) => void;
  /** 「查看全部」→ Report tab（宿主未提供导航能力时禁用并说明） */
  onOpenReport?: () => void;
}

function severityClass(severity: string): string {
  return severity === 'critical' ? 'text-rose-600' : 'text-amber-600';
}

/**
 * 我的异常订单摘要（210 §4.11）：计数分档 + 按规则 Top 5 + 订单 Top 5 + 「查看全部」。
 *
 * 计数口径来自后端 `anomaly_summary`（命中阈值规则 ∪ overfill ∪ cost_missing，
 * 订单级评估）；本组件不重算、不合并规则。Report 异常表是**路由级全市场口径**，
 * 与本表存在「订单 vs 路由」差异，链接旁必须注明（见文案）。
 */
export function AnomalySummary({ summary, onSelectOrder, onOpenReport }: AnomalySummaryProps) {
  const rules = summary.by_rule.slice(0, RULE_TOP_N);
  const topOrders = summary.top_orders.slice(0, RULE_TOP_N);
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="flex items-center gap-2 text-sm">
            <AlertOctagon className="h-4 w-4 text-amber-500" />
            我的异常订单
            <span className="font-normal text-muted-foreground">
              {summary.orders_total.toLocaleString()} 单
            </span>
            <span className="text-[11px] font-normal text-rose-600">
              critical {summary.critical.toLocaleString()}
            </span>
            <span className="text-[11px] font-normal text-amber-600">
              warning {summary.warning.toLocaleString()}
            </span>
          </CardTitle>
          <Button
            variant="outline"
            size="sm"
            className="h-7 gap-1 text-[11px]"
            disabled={!onOpenReport}
            title={
              onOpenReport
                ? 'Report 异常表为路由级全市场口径，与本表（订单级）存在计数差异'
                : '当前宿主未提供跨 tab 导航'
            }
            onClick={onOpenReport}
          >
            查看全部
            <ArrowRight className="h-3 w-3" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-2">
        {summary.orders_total === 0 ? (
          <p className="text-xs text-muted-foreground">当前筛选范围无异常订单（订单级口径）。</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <div className="mb-1 text-[11px] font-medium text-muted-foreground">
                按规则（Top {RULE_TOP_N}）
              </div>
              <ul className="space-y-1 text-xs">
                {rules.map((rule) => (
                  <li key={rule.key} className="flex items-center justify-between gap-2">
                    <span className="truncate" title={rule.label}>{rule.label}</span>
                    <span className="shrink-0 tabular-nums text-muted-foreground">
                      {rule.count.toLocaleString()}
                      {rule.critical > 0 && (
                        <span className="ml-1 text-rose-600">（critical {rule.critical}）</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <div className="mb-1 text-[11px] font-medium text-muted-foreground">
                异常订单（Top {RULE_TOP_N}）
              </div>
              <ul className="space-y-1 text-xs">
                {topOrders.map((order) => (
                  <li key={`${order.order_id}|${order.order_as_of_date}`}>
                    <button
                      type="button"
                      className="flex w-full items-center justify-between gap-2 rounded px-1 py-0.5 text-left hover:bg-muted/60"
                      onClick={() => onSelectOrder?.(order.order_id, order.order_as_of_date)}
                      disabled={!onSelectOrder}
                      title={order.reasons.map((reason) => reason.label).join('、')}
                    >
                      <span className="truncate font-mono">{order.order_id}</span>
                      <span className="shrink-0 text-[11px] text-muted-foreground">
                        {order.ticker ?? '—'} · {order.side ?? '—'}
                      </span>
                      <span className={`shrink-0 text-[11px] ${severityClass(order.severity)}`}>
                        {order.reasons.length} 项
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          口径：{summary.note}。规则命中 {summary.rule_orders.toLocaleString()} 单、质量标记{' '}
          {summary.quality_orders.toLocaleString()} 单，两者可能重叠，合计
          {` ${summary.orders_total.toLocaleString()} 单`}（去重）。
        </p>
      </CardContent>
    </Card>
  );
}
