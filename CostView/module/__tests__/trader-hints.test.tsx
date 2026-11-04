import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { HintCards } from '../components/trader/HintCards';
import type { TraderHint } from '../types';

const H4: TraderHint = {
  rule_id: 'H4',
  title: '释放延迟偏高（线索）',
  evidence: { route_to_first_fill_sec: 4060, peer_p90_sec: 3863 },
  peer_n: 54,
  confidence: 'high',
  action: '复核路由下达→首笔',
};

const H7: TraderHint = {
  rule_id: 'H7',
  title: '单笔成交，节奏不可评估',
  evidence: { fill_count: 1, completion: 0.5 },
  peer_n: 0,
  confidence: 'self',
  action: '确认是否本应拆分执行',
};

describe('HintCards（210 §4.8）', () => {
  it('渲染规则号 / 证据 / 置信度 / 建议动作，语气是「需复核」', () => {
    render(<HintCards hints={[H4, H7]} />);

    expect(screen.getByText('改进提示（线索，需复核）')).toBeInTheDocument();
    expect(screen.getByText('H4')).toBeInTheDocument();
    expect(screen.getByText(/high · n=54/)).toBeInTheDocument();
    // 证据带单位标签与数值
    expect(screen.getByText(/路由→首笔 \(s\)：/)).toBeInTheDocument();
    // formatNum 对整数不带小数位（toLocaleString maximumFractionDigits: 2）
    expect(screen.getAllByText('4,060').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/建议动作：复核路由下达→首笔/)).toBeInTheDocument();
    // 自身样本规则：置信度显示「自身样本」而不是 n=0
    expect(screen.getByText('自身样本')).toBeInTheDocument();
    expect(screen.queryByText(/n=0/)).not.toBeInTheDocument();
  });

  it('「定位时间线」按钮回调当前提示（未提供回调时禁用）', async () => {
    const user = userEvent.setup();
    const onLocate = vi.fn();
    const { rerender } = render(<HintCards hints={[H4]} onLocateTimeline={onLocate} />);

    await user.click(screen.getByRole('button', { name: /定位时间线/ }));
    expect(onLocate).toHaveBeenCalledWith(H4);

    rerender(<HintCards hints={[H4]} />);
    expect(screen.getByRole('button', { name: /定位时间线/ })).toBeDisabled();
  });

  it('空列表：显式说明已评估与未落地范围，不读作「没检查」', () => {
    render(<HintCards hints={[]} />);

    expect(
      screen.getByText(/未触发改进提示（已评估 H1 \/ H4 \/ H7；H2 \/ H5 \/ H6 未落地/),
    ).toBeInTheDocument();
  });
});
