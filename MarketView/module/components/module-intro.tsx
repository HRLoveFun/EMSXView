// 模块头部：极简一行（模块名 + 标题 + 一句话），不再铺三张能力卡片，减少首屏占用
export const ModuleIntro = () => (
  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
    <span className="text-[11px] font-medium uppercase tracking-[0.24em] text-muted-foreground">
      MarketView
    </span>
    <h2 className="text-base font-semibold text-foreground">Pre-trade monitor</h2>
    <p className="text-xs text-muted-foreground">
      高亮异常（Liquidity / Volatility / Risk notes）+ 监控表；点击行查看价格—量分布、累计量与占比。
    </p>
  </div>
);
