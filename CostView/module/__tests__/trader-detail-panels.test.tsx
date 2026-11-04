import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { FillStatsPanel } from '../components/trader/FillStatsPanel';
import { LatencyBreakdown } from '../components/trader/LatencyBreakdown';
import { PassiveSplitPanel } from '../components/trader/PassiveSplitPanel';
import type { TraderFillStats, TraderLatency, TraderLiquiditySplit } from '../types';

const STATS: TraderFillStats = {
  median: 3500, p90: 3900, cv: 0.14, max_fill_ratio: 0.33,
  top3_share: 0.82, fills_per_min: 0.4,
};

const LIQUIDITY: TraderLiquiditySplit = {
  passive_share_strict: 0.5, aggressive_share_strict: 0.3,
  auction_share: 0.1, unknown_share: 0.1,
  passive_cost_bps: -3.0, aggressive_cost_bps: -5.0,
  recognized_share: 0.9, total_shares: 7000, mapping: 'fix851_strict',
};

const LATENCY: TraderLatency = {
  order_to_route_sec: 1.2, route_to_first_fill_sec: 30,
  order_to_first_fill_sec: 31.2, first_continuous_fill_sec: 25,
  scheduled: false, latency_anomaly: false,
};

describe('FillStatsPanel（210 §4.5）', () => {
  it('渲染六项统计并给出线索（6 笔且集中）', () => {
    render(<FillStatsPanel stats={STATS} fillCount={8} />);

    expect(screen.getByText('单次填充量分布')).toBeInTheDocument();
    expect(screen.getByText('3.5K')).toBeInTheDocument();        // 中位 3,500（千分位简写）
    expect(screen.getByText('0.14')).toBeInTheDocument();        // 单笔 CV
    expect(screen.getByText('33.00%')).toBeInTheDocument();      // 最大单笔 / 委托
    expect(screen.getByText('82.00%')).toBeInTheDocument();      // top3
    expect(screen.getByText('集中扫单 / 切片不均（线索）')).toBeInTheDocument();
  });

  it('单笔成交：CV / Top3 显示 N/A 且不出现扫单线索', () => {
    render(
      <FillStatsPanel
        stats={{ ...STATS, cv: null, top3_share: null }}
        fillCount={1}
      />,
    );

    expect(screen.getAllByText('N/A').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText(/集中扫单/)).not.toBeInTheDocument();
  });

  it('样本不足（<6 笔）即使集中也不提示', () => {
    render(<FillStatsPanel stats={STATS} fillCount={3} />);

    expect(screen.queryByText(/集中扫单/)).not.toBeInTheDocument();
  });
});

describe('PassiveSplitPanel（210 §4.6）', () => {
  it('渲染四档占比、成本差与已知映射说明', () => {
    render(<PassiveSplitPanel liquidity={LIQUIDITY} />);

    expect(screen.getByText('被动')).toBeInTheDocument();
    expect(screen.getByText('主动')).toBeInTheDocument();
    expect(screen.getByText('竞价')).toBeInTheDocument();
    expect(screen.getByText('未知')).toBeInTheDocument();
    // 成本差 = -3 − (-5) = +2.00 bps（被动更优）
    expect(screen.getByText('+2.00 bps')).toBeInTheDocument();
    expect(screen.getByText(/已识别占比/)).toBeInTheDocument();
    expect(screen.getByText(/fix851_strict/)).toBeInTheDocument();
  });

  it('未知占比 >10% 才打标，>25% 升级为 warn 文案', () => {
    const { rerender } = render(
      <PassiveSplitPanel liquidity={{ ...LIQUIDITY, unknown_share: 0.1 }} />,
    );
    expect(screen.queryByText(/未识别/)).not.toBeInTheDocument();

    rerender(<PassiveSplitPanel liquidity={{ ...LIQUIDITY, unknown_share: 0.38 }} />);
    expect(screen.getByText(/未识别 38.00%/)).toBeInTheDocument();
  });
});

describe('LatencyBreakdown（210 §4.9）', () => {
  it('渲染三段延迟与首笔偏移', () => {
    render(<LatencyBreakdown latency={LATENCY} />);

    expect(screen.getByText('下达 → 路由')).toBeInTheDocument();
    expect(screen.getByText('1.2s')).toBeInTheDocument();
    expect(screen.getByText('30.0s')).toBeInTheDocument();
    expect(screen.getByText('31.2s')).toBeInTheDocument();
    expect(screen.queryByText(/按计划在收盘竞价成交/)).not.toBeInTheDocument();
  });

  it('收盘/竞价单：显示「按计划成交」，不把排程读成延迟异常', () => {
    render(<LatencyBreakdown latency={{ ...LATENCY, scheduled: true }} />);

    expect(screen.getByText(/按计划在收盘竞价成交/)).toBeInTheDocument();
    expect(screen.queryByText(/早于路由下达/)).not.toBeInTheDocument();
  });

  it('负延迟异常单独标红；不可得显示「—」', () => {
    render(
      <LatencyBreakdown
        latency={{ ...LATENCY, latency_anomaly: true, order_to_route_sec: null }}
      />,
    );

    expect(screen.getByText(/首笔非竞价成交早于路由下达/)).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1);
  });
});
