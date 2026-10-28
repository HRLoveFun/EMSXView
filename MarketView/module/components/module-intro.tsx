import { Activity, Gauge, LineChart } from 'lucide-react';

// 模块能力说明卡片配置（纯展示，无外部依赖）
const capabilityCards = [
  {
    title: 'Pool-driven scope',
    description:
      'The board reports exactly the pool it was built from: index constituents once the constituent table lands, the 8-ticker dev-validation list until then. Pool id, source and as_of travel with every response.',
    icon: Activity,
  },
  {
    title: 'One source for alerts',
    description:
      'Liquidity, Volatility and Risk notes are projections of the same assembled rows, so the highlight panel and the table can never disagree about a ticker.',
    icon: Gauge,
  },
  {
    title: 'Price × volume detail',
    description:
      'Clicking a row opens a shared time axis: the 10-minute price-volume distribution with OHLC levels, cumulative volume versus the prior five sessions, and the cumulative share curve.',
    icon: LineChart,
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
        <h2 className="text-2xl font-semibold tracking-tight text-foreground">Pre-trade monitor</h2>
        <p className="max-w-3xl text-sm leading-6 text-muted-foreground">
          One highlight panel plus one table. The panel answers “which names need attention today” for
          liquidity, volatility and data risk; the table carries the full metric set per name. Every
          number states its own as-of date and source — missing data is shown as missing, never as zero.
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
