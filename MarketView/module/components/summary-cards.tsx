// 盘前工作台顶部统计卡片：可见行数、风险告警计数与 handoff 候选发送
interface LastHandoffSummary {
  rowCount: number;
  generatedAt: string;
}

interface SummaryCardsProps {
  rowCount: number;
  criticalCount: number;
  warningCount: number;
  handoffRowCount: number;
  hasExplicitSelection: boolean;
  isPublishing: boolean;
  canPublish: boolean;
  publishStatus: string | null;
  lastHandoff: LastHandoffSummary | null;
  onPublish: () => void;
}

// 统计卡片组：数据概览 + handoff 发送入口
export const SummaryCards = ({
  rowCount,
  criticalCount,
  warningCount,
  handoffRowCount,
  hasExplicitSelection,
  isPublishing,
  canPublish,
  publishStatus,
  lastHandoff,
  onPublish,
}: SummaryCardsProps) => (
  <div className="grid gap-4 lg:grid-cols-4">
    <article className="rounded-2xl border border-border/70 bg-background/70 p-5">
      <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Visible rows</div>
      <div className="mt-3 text-3xl font-semibold text-foreground">{rowCount}</div>
      <p className="mt-2 text-sm text-muted-foreground">Number of candidates in the current stock pool after filtering and sorting.</p>
    </article>

    <article className="rounded-2xl border border-red-500/20 bg-red-500/5 p-5">
      <div className="text-xs uppercase tracking-[0.2em] text-red-700/80">Critical alerts</div>
      <div className="mt-3 text-3xl font-semibold text-red-700">{criticalCount}</div>
      <p className="mt-2 text-sm text-red-700/80">Number of symbols reaching critical level on any dimension.</p>
    </article>

    <article className="rounded-2xl border border-amber-500/20 bg-amber-500/5 p-5">
      <div className="text-xs uppercase tracking-[0.2em] text-amber-700/80">Warning alerts</div>
      <div className="mt-3 text-3xl font-semibold text-amber-700">{warningCount}</div>
      <p className="mt-2 text-sm text-amber-700/80">Symbols with at least one warning but not reaching critical level, worth pre-trade attention.</p>
    </article>

    <article className="rounded-2xl border border-border/70 bg-background/70 p-5">
      <div className="text-xs uppercase tracking-[0.2em] text-muted-foreground">Hand-off candidates</div>
      <div className="mt-3 text-3xl font-semibold text-foreground">{handoffRowCount}</div>
      <p className="mt-2 text-sm text-muted-foreground">
        {hasExplicitSelection ? 'Handoff payload generated based on explicitly selected tickers.' : 'Defaults to current filter results when nothing is selected.'}
      </p>
      <button
        type="button"
        className="mt-3 inline-flex items-center gap-2 rounded-lg border border-primary/60 bg-primary/10 px-3 py-1.5 text-xs font-medium text-primary transition hover:bg-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
        disabled={isPublishing || !canPublish}
        onClick={onPublish}
      >
        {isPublishing ? 'Sending…' : 'Send to ExecutionView →'}
      </button>
      {publishStatus && (
        <p className="mt-2 text-xs text-muted-foreground">{publishStatus}</p>
      )}
      {lastHandoff && (
        <p className="mt-1 text-[11px] text-muted-foreground">
          Last handoff: {lastHandoff.rowCount} candidates,
          {new Date(lastHandoff.generatedAt).toLocaleString()}
        </p>
      )}
    </article>
  </div>
);
