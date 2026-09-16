import { Activity, ArrowUpDown, Gauge } from 'lucide-react';

// 模块能力说明卡片配置（纯展示，无外部依赖）
const capabilityCards = [
  {
    title: 'Stock Pools',
    description: 'Stock pool definitions are centralized on the MarketView contract, driven by a single daily snapshot path rather than scattered across local page state.',
    icon: Activity,
  },
  {
    title: 'Risk Filters',
    description: 'Pre-market screening by ADV, daily volume, daily volatility, and intraday volatility, with direct exposure of liquidity and volatility alert levels.',
    icon: Gauge,
  },
  {
    title: 'Candidate Hand-Off',
    description: 'Candidate payload already has a clear contract and can be handed off to ExecutionView without requiring a recommendation model.',
    icon: ArrowUpDown,
  },
];

// 模块头部：标题、简介与能力卡片
export const ModuleIntro = () => (
  <>
    <div className="space-y-3">
      <div className="inline-flex items-center rounded-full border border-border bg-background px-3 py-1 text-xs font-medium uppercase tracking-[0.24em] text-muted-foreground">
        MarketView
      </div>
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">Pre-trade workspace</h2>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          Here we continue to use the same daily snapshot path, but it is no longer just a fixed table. MarketView now uses stock pools as the entry point, bringing together filtering, sorting, liquidity and volatility alerts, and the candidate contract for subsequent handoff into a pre-trade workspace.
        </p>
      </div>
    </div>

    <div className="grid gap-4 lg:grid-cols-3">
      {capabilityCards.map((card) => (
        <article key={card.title} className="rounded-2xl border border-border/70 bg-background/80 p-5">
          <card.icon className="h-5 w-5 text-primary" />
          <h3 className="mt-4 text-base font-semibold text-foreground">{card.title}</h3>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">{card.description}</p>
        </article>
      ))}
    </div>
  </>
);
