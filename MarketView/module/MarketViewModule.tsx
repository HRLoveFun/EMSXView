import { useCallback, useMemo, useState } from 'react';

import { ModuleIntro } from './components/module-intro';
import { MonitorBoardPanel } from './components/monitor-board-panel';
import { TickerDetailDrawer } from './components/ticker-detail-drawer';
import { buildLiveQuotes } from './lib/workspace';
import { useMarketStateStream } from './hooks/use-market-state-stream';
import { useSecurityNames } from './hooks/use-security-names';

/**
 * MarketView 交易前监控台（057 节点一重定义）。
 *
 * 页面只有两块：高亮信息面板（Liquidity / Volatility / Risk notes）+ 监控表；
 * 点击任意行弹出三联图详情。证券范围由后端池决定（当前为开发验证 8 个 ticker），
 * 前端拿到行清单后统一订阅实时行情并解析中文简称。
 */
export default function MarketViewModule() {
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [universe, setUniverse] = useState<string[]>([]);

  // 池成员登记：面板刷新时把行清单上报，供 WS 订阅与 refdata 取名共用
  const handleUniverseChange = useCallback((tickers: string[]) => {
    setUniverse((current) => {
      const unchanged =
        current.length === tickers.length && current.every((ticker, index) => ticker === tickers[index]);
      return unchanged ? current : tickers;
    });
  }, []);

  const securityNames = useSecurityNames(universe);
  const liveState = useMarketStateStream(universe);
  const live = useMemo(
    () => buildLiveQuotes(liveState.snapshot, liveState.status),
    [liveState.snapshot, liveState.status],
  );

  return (
    <section className="space-y-6 rounded-2xl border bg-card p-6 shadow-sm">
      <ModuleIntro />

      <MonitorBoardPanel
        live={live}
        names={securityNames}
        selectedTicker={selectedTicker}
        onSelectTicker={setSelectedTicker}
        onUniverseChange={handleUniverseChange}
      />

      {selectedTicker ? (
        <TickerDetailDrawer ticker={selectedTicker} onClose={() => setSelectedTicker(null)} />
      ) : null}
    </section>
  );
}
