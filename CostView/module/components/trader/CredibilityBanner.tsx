import { useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronUp, CircleSlash } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { TraderProbeCheck } from '../../types';

/** 四类检查的中文名（与后端 compute_probes 的 id 一一对应） */
const CHECK_LABELS: Record<string, string> = {
  quantity: '数量矛盾',
  participation: '参与率异常',
  cost_missing: '成本字段缺失',
  fill_quality: '逐笔质量',
};

/** 受影响 KPI 的中文名（来源：§4.12 横幅表格 + 探针 payload 的 affected_kpis） */
const KPI_LABELS: Record<string, string> = {
  completion: '完成率',
  opportunity_cost: '机会成本',
  par_rate: '参与率',
  anomaly_orders: '异常数',
  arrival_cost_bps: 'arrival',
  wagner_is_bps: 'IS 成本',
  passive_ratio: '被动占比',
  peer_percentile: 'peer 分位',
  release_delay: '释放延迟',
  peer_percentile_adverse: 'peer 分位',
};

/** 检查项状态：hit 触发 / ok 通过 / unchecked 未检查（三态，禁止把未检查画成通过） */
type CheckState = 'hit' | 'ok' | 'unchecked';

function stateOf(check: TraderProbeCheck): CheckState {
  if (!check.checked) return 'unchecked';
  return (check.triggered ?? 0) > 0 ? 'hit' : 'ok';
}

function kpiLabels(keys: string[]): string {
  return keys.map((key) => KPI_LABELS[key] ?? key).join('、');
}

/** 单条检查的芯片（摘要行用） */
function CheckChip({ check }: { check: TraderProbeCheck }) {
  const state = stateOf(check);
  const label = CHECK_LABELS[check.id] ?? check.id;
  if (state === 'unchecked') {
    return (
      <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground">
        <CircleSlash className="h-3 w-3" />
        {label} 未检查
      </span>
    );
  }
  const triggered = check.triggered ?? 0;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] ${
        state === 'hit'
          ? 'bg-amber-100 text-amber-700'
          : 'bg-emerald-100 text-emerald-700'
      }`}
      title={check.affected_kpis.length ? `影响：${kpiLabels(check.affected_kpis)}` : undefined}
    >
      {state === 'hit' ? <AlertTriangle className="h-3 w-3" /> : <CheckCircle2 className="h-3 w-3" />}
      {label} {triggered > 0 ? triggered.toLocaleString() : '通过'}
    </span>
  );
}

/** 展开后的单条明细：状态 + 受影响 KPI + 口径说明 */
function CheckDetail({ check }: { check: TraderProbeCheck }) {
  const state = stateOf(check);
  const label = CHECK_LABELS[check.id] ?? check.id;
  return (
    <div className="flex items-start justify-between gap-3 border-t py-1.5 text-xs first:border-t-0">
      <div className="space-y-0.5">
        <div className="font-medium">
          {label}
          {state === 'unchecked' && <span className="ml-1 text-muted-foreground">未检查</span>}
        </div>
        <div className="text-muted-foreground">
          {check.affected_kpis.length > 0
            ? `影响 KPI：${kpiLabels(check.affected_kpis)}`
            : '无受影响 KPI'}
        </div>
        {check.note && <div className="text-amber-600">{check.note}</div>}
      </div>
      <div className="shrink-0 tabular-nums text-muted-foreground">
        {state === 'unchecked' ? '—' : `${(check.triggered ?? 0).toLocaleString()} 单`}
      </div>
    </div>
  );
}

/**
 * 全局可信度横幅（210 §4.12）：四类检查**始终渲染**，可折叠展开到口径与受影响 KPI。
 *
 * 三条硬规则：
 * 1. 0 触发也显示，文案为「N 类检查全部通过」，不因全绿而隐藏；
 * 2. `checked=false`（如范围 >31 天时的逐笔质量）一律显示「未检查」，不进「通过」计数；
 * 3. 折叠只影响明细可见性，摘要行（已检查 / 触发 / 影响 KPI 数）永远可见。
 */
export function CredibilityBanner({ checks }: { checks: TraderProbeCheck[] }) {
  const [expanded, setExpanded] = useState(false);
  if (checks.length === 0) return null;
  const checked = checks.filter((check) => check.checked);
  const triggered = checked.filter((check) => (check.triggered ?? 0) > 0);
  const affected = new Set(triggered.flatMap((check) => check.affected_kpis));
  const headline = triggered.length === 0
    ? `${checked.length} 类检查全部通过${checks.length > checked.length ? `（${checks.length - checked.length} 类未检查）` : ''}`
    : `已检查 ${checked.length}/${checks.length} 类 · 触发 ${triggered.length} 类 · 影响 ${affected.size} 个 KPI`;

  return (
    <Card>
      <CardContent className="space-y-2 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-medium">数据可信度</span>
            <span className={`text-xs ${triggered.length ? 'text-amber-600' : 'text-emerald-600'}`}>
              {headline}
            </span>
          </div>
          <Button
            variant="ghost"
            size="sm"
            className="h-6 gap-1 px-2 text-[11px]"
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            {expanded ? '收起口径' : '展开口径'}
          </Button>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {checks.map((check) => (
            <CheckChip key={check.id} check={check} />
          ))}
        </div>
        {expanded && (
          <div className="space-y-0.5 rounded border bg-muted/30 p-2">
            {checks.map((check) => (
              <CheckDetail key={check.id} check={check} />
            ))}
            <p className="pt-1 text-[11px] text-muted-foreground">
              0 触发不等于数据无缺陷；未检查项不计入「通过」，口径见各项说明。
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
