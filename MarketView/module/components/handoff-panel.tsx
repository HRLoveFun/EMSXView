import type { MarketCandidatePayload } from '../types';

interface HandoffPanelProps {
  payload: MarketCandidatePayload | null;
}

// handoff 契约预览侧栏：展示将发送给 ExecutionView 的候选负载
export const HandoffPanel = ({ payload }: HandoffPanelProps) => (
  <aside className="space-y-4 rounded-xl border border-border bg-background/90 p-4">
    <div>
      <p className="text-sm font-medium text-foreground">ExecutionView hand-off preview</p>
      <p className="mt-1 text-sm leading-6 text-muted-foreground">
        This is the candidate payload contract reserved for ExecutionView. When nothing is selected, the current filter results are used; when tickers are selected, only the explicit candidates are included.
      </p>
    </div>

    <div className="rounded-xl border border-border/70 bg-muted/20 p-4 text-sm">
      <div className="flex items-center justify-between gap-3">
        <span className="text-muted-foreground">Payload source</span>
        <span className="font-medium text-foreground">{payload?.source ?? 'N/A'}</span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-muted-foreground">Handoff target</span>
        <span className="font-medium text-foreground">{payload?.handoff_target ?? 'N/A'}</span>
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-muted-foreground">Candidate count</span>
        <span className="font-medium text-foreground">{payload?.row_count ?? 0}</span>
      </div>
    </div>

    <div className="rounded-xl border border-border/70 bg-background p-4">
      <pre className="max-h-[420px] overflow-auto whitespace-pre-wrap break-all text-xs leading-5 text-muted-foreground">
        {payload ? JSON.stringify(payload, null, 2) : 'No candidate payload available.'}
      </pre>
    </div>

    <div className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
      The current contract only carries daily candidates and risk labels. It does not derive execution recommendations, nor does it mistake the snapshot for a real-time market data stream.
    </div>
  </aside>
);
