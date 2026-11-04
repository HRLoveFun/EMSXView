import { Crosshair } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { formatNum } from '../../lib/report-format';
import type { TraderHint } from '../../types';

/** 证据字段 → 展示名（单位在文案里带上，避免读数字猜量纲） */
const EVIDENCE_LABELS: Record<string, string> = {
  completion: '完成率',
  opp_bps: '机会成本 (bps)',
  arrival_bps: 'arrival (bps)',
  peer_p25_opp_bps: '同类 p25 机会成本 (bps)',
  route_to_first_fill_sec: '路由→首笔 (s)',
  peer_p90_sec: '同类 p90 (s)',
  fill_count: '成交笔数',
};

const CONFIDENCE_VARIANT: Record<string, string> = {
  high: 'bg-emerald-100 text-emerald-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-muted text-muted-foreground',
  self: 'bg-sky-100 text-sky-700',
};

interface HintCardsProps {
  hints: TraderHint[];
  /** 点击「定位时间线」：由详情卡滚动到时间线区块（未提供时按钮禁用） */
  onLocateTimeline?: (hint: TraderHint) => void;
}

/** 单条提示卡：证据齐才渲染（后端保证），前端只做格式化与文案 */
function HintCard({
  hint,
  onLocateTimeline,
}: {
  hint: TraderHint;
  onLocateTimeline?: (hint: TraderHint) => void;
}) {
  const entries = Object.entries(hint.evidence);
  return (
    <div className="rounded border p-2 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-medium">
          <span className="mr-1 font-mono text-muted-foreground">{hint.rule_id}</span>
          {hint.title}
        </span>
        <span
          className={`rounded px-1.5 py-0.5 text-[11px] ${
            CONFIDENCE_VARIANT[hint.confidence] ?? CONFIDENCE_VARIANT.low
          }`}
          title={
            hint.confidence === 'self'
              ? '自身样本（无 peer 依赖）'
              : '同类样本 n≥50 high / n≥20 medium / 否则 low'
          }
        >
          {hint.confidence === 'self' ? '自身样本' : `${hint.confidence} · n=${hint.peer_n}`}
        </span>
      </div>
      <ul className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 sm:grid-cols-4">
        {entries.map(([key, value]) => (
          <li key={key} className="text-muted-foreground">
            {EVIDENCE_LABELS[key] ?? key}：
            <span className="font-medium text-foreground">
              {value == null ? 'N/A' : formatNum(value)}
            </span>
          </li>
        ))}
      </ul>
      <div className="mt-1 flex items-center justify-between gap-2">
        <span className="text-amber-700">建议动作：{hint.action}</span>
        <Button
          variant="ghost"
          size="sm"
          className="h-6 gap-1 px-2 text-[11px]"
          disabled={!onLocateTimeline}
          onClick={() => onLocateTimeline?.(hint)}
          title="滚动到执行时间线，对照该提示的时点证据"
        >
          <Crosshair className="h-3 w-3" />
          定位时间线
        </Button>
      </div>
    </div>
  );
}

/**
 * 改进提示卡组（210 §4.8）：语气是「线索 / 需复核」，不写「应该用 X 算法」。
 *
 * 每条提示由后端保证字段齐全（缺证据即不产出）；空列表时显式说明已评估与未落地的
 * 规则范围，避免把「没触发」读成「没有检查」。
 */
export function HintCards({ hints, onLocateTimeline }: HintCardsProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">改进提示（线索，需复核）</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {hints.length === 0 ? (
          <p className="text-xs text-muted-foreground">
            未触发改进提示（已评估 H1 / H4 / H7；H2 / H5 / H6 未落地，原因见同类分位的
            口径说明）。
          </p>
        ) : (
          hints.map((hint) => (
            <HintCard key={hint.rule_id} hint={hint} onLocateTimeline={onLocateTimeline} />
          ))
        )}
      </CardContent>
    </Card>
  );
}
