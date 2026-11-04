import { AlertCircle, Loader2, X } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  formatDuration,
  formatInt,
  formatMoneyWithCcy,
  formatNum,
  formatPct,
  formatShares,
} from '../../lib/report-format';
import { costToneClass, formatSignedBps } from '../../lib/cost-sign';
import type { TraderOrderDetail, TraderQualityEntry } from '../../types';
import { CostBreakdownBar } from './CostBreakdownBar';
import { CompletionTrajectory } from './CompletionTrajectory';
import { ExecutionTimeline } from './ExecutionTimeline';

/** 时间桶可选项（与后端 trader_metrics.BUCKET_MINUTES 白名单一致） */
const BUCKET_OPTIONS: number[] = [5, 15];

const SEVERITY_VARIANT: Record<string, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  bad: 'destructive',
  warn: 'secondary',
  info: 'outline',
};
const FLAG_LABELS: Record<string, string> = {
  overfill: '超成交',
  amount_qty_mismatch: '委托股数矛盾',
  cost_missing: '成本缺失',
  par_suspect: '参与率失真',
  single_fill: '单笔成交',
  liquidity_unknown: '流动性未识别',
  latency_anomaly: '延迟异常',
  scheduled_close: '收盘竞价',
};

interface OrderReviewCardProps {
  detail: TraderOrderDetail | null;
  isLoading: boolean;
  error: Error | null;
  bucketMin: number;
  onBucketMinChange: (value: number) => void;
  onClose: () => void;
  onRetry: () => void;
}

/** 质量徽章组（详情口径：带 severity 与说明，与列表的字符串数组不同） */
function QualityBadges({ entry }: { entry: TraderQualityEntry }) {
  return (
    <Badge
      variant={SEVERITY_VARIANT[entry.severity] ?? 'outline'}
      title={entry.detail ?? undefined}
    >
      {FLAG_LABELS[entry.id] ?? entry.id}
    </Badge>
  );
}

/** 详情卡头：订单身份 + 关键数字（成交 / 完成率 / VWAP / arrival / 跨度） */
function CardSummary({ detail }: { detail: TraderOrderDetail }) {
  const order = detail.order;
  return (
    <>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span className="font-mono text-sm text-foreground">{order.order_id}</span>
        <span>{order.order_as_of_date}</span>
        <span>{order.equ_ticker ?? '—'}</span>
        <span>{order.exchange ?? '—'}</span>
        <span>{order.side ?? '—'}</span>
        <span>{order.algo ?? '—'}</span>
        <span>{order.broker ?? '—'}</span>
        <span>{order.trader_name ?? '—'}</span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4 lg:grid-cols-7">
        <div>
          <div className="text-[11px] text-muted-foreground">委托 / 成交股数</div>
          <div>{formatShares(order.route_shares)} / {formatShares(order.fill)}</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">完成率</div>
          <div>{formatPct(order.completion)}</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">VWAP</div>
          <div>{formatNum(order.vwap)}</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">arrival（负 = 不利）</div>
          <div className={costToneClass(order.arrival_cost_bps)}>
            {formatSignedBps(order.arrival_cost_bps)}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">机会成本</div>
          <div className={costToneClass(order.opportunity_cost)}>
            {formatMoneyWithCcy(order.opportunity_cost, order.currency)}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">路由 / 成交笔数</div>
          <div>{formatInt(order.route_count)} / {formatInt(order.fill_count)}</div>
        </div>
        <div>
          <div className="text-[11px] text-muted-foreground">订单历时</div>
          <div>{formatDuration(order.order_duration_sec)}</div>
        </div>
      </div>
    </>
  );
}

/**
 * 订单详情卡（210 PR-4 / §3.5）：容器 + 分区，不做交互式展开。
 *
 * 时间线 / 成本分解 / 完成轨迹三段各自只消费后端 `GET /orders/{order_id}` 的同一份
 * payload，前端不重算任何 KPI（完成率、bps、参与率均由后端给出）。
 */
export function OrderReviewCard({
  detail,
  isLoading,
  error,
  bucketMin,
  onBucketMinChange,
  onClose,
  onRetry,
}: OrderReviewCardProps) {
  const quality = detail?.quality;
  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="text-sm">
            订单详情
            {isLoading && detail && (
              <span className="ml-2 text-[11px] font-normal text-muted-foreground">更新中…</span>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-muted-foreground">时间桶</span>
            {BUCKET_OPTIONS.map((value) => (
              <Button
                key={value}
                size="sm"
                variant={value === bucketMin ? 'default' : 'outline'}
                onClick={() => onBucketMinChange(value)}
              >
                {value} 分钟
              </Button>
            ))}
            <Button size="sm" variant="ghost" onClick={onClose} aria-label="关闭详情">
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading && !detail && (
          <div className="flex h-24 items-center justify-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            正在加载订单详情…
          </div>
        )}

        {error && (
          <div className="flex items-center justify-between gap-2 rounded border border-destructive/40 p-2 text-xs">
            <span className="flex items-center gap-1 text-destructive">
              <AlertCircle className="h-4 w-4" />
              详情加载失败：{error.message}
            </span>
            <Button size="sm" variant="outline" onClick={onRetry}>重试</Button>
          </div>
        )}

        {detail && (
          <>
            <CardSummary detail={detail} />
            {quality && quality.flags.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {quality.flags.map((entry) => (
                  <QualityBadges key={`${entry.id}-${entry.detail ?? ''}`} entry={entry} />
                ))}
              </div>
            )}
            <CostBreakdownBar cost={detail.cost} completion={detail.order.completion} />
            <CompletionTrajectory detail={detail} />
            <ExecutionTimeline detail={detail} />
          </>
        )}
      </CardContent>
    </Card>
  );
}
