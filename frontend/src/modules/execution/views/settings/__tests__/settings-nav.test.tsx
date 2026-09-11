/**
 * SettingsNav 渲染基准（React.Profiler）—— code-cleanup skill 前端实测方案 A。
 *
 * 目的：在没有 React DevTools 的环境（无插件/无法录制）下，用可回归的测试量化
 * 「重渲染次数与渲染耗时」，对应 skill 的 PF-07（index key / 列表内联 props）与
 * PF-08（Context 未 memo 化）实测判定。
 *
 * 运行：npm test
 */
import { Profiler, type ProfilerOnRenderCallback, type ReactElement } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { SettingsNav } from '../SettingsNav';

interface Commit {
  phase: 'mount' | 'update' | 'nested-update';
  actualDuration: number;
}

/**
 * 在 React.Profiler 内渲染并记录每次 commit。
 * `actualDuration` 是本次 commit 的渲染耗时（React 自己的计时，不含 layout/paint）。
 */
export function measure(
  ui: ReactElement,
  onRender: ProfilerOnRenderCallback,
): { rerender: (next: ReactElement) => void } {
  const wrapped = <Profiler id="target" onRender={onRender}>{ui}</Profiler>;
  const utils = render(wrapped);
  return {
    rerender: (next: ReactElement) => {
      utils.rerender(<Profiler id="target" onRender={onRender}>{next}</Profiler>);
    },
  };
}

describe('SettingsNav（React.Profiler 渲染基准）', () => {
  it('mount 产生 1 次 commit，父组件重渲染再产生 1 次', () => {
    const commits: Commit[] = [];
    const onRender: ProfilerOnRenderCallback = (_id, phase, actualDuration) => {
      commits.push({ phase, actualDuration });
    };
    const onNavigate = vi.fn();

    const utils = render(
      <Profiler id="target" onRender={onRender}>
        <SettingsNav activeSection="global" onNavigate={onNavigate} />
      </Profiler>,
    );
    expect(commits).toHaveLength(1);
    expect(commits[0].phase).toBe('mount');

    // 父组件重渲染（Props 相同）→ 无 memo 的函数组件会再次渲染
    utils.rerender(
      <Profiler id="target" onRender={onRender}>
        <SettingsNav activeSection="global" onNavigate={onNavigate} />
      </Profiler>,
    );
    expect(commits).toHaveLength(2);
    expect(commits[1].phase).toBe('update');
  });

  it('导航点击正确回调（功能正确性）', () => {
    const onNavigate = vi.fn();
    render(<SettingsNav activeSection="global" onNavigate={onNavigate} />);

    fireEvent.click(screen.getByRole('button', { name: 'Monitor Conditions' }));
    expect(onNavigate).toHaveBeenCalledWith('monitor-conditions');

    // 8 个导航项都有稳定 key（item.id），不使用数组下标 —— PF-07 的该形态在本组件不存在
    const items = ['Global', 'Monitor Conditions', 'Broker & Algorithm',
      'Market Broker Mapping', 'Parameter Frequency', 'Route Plans',
      'Strategy Data', 'About'];
    items.forEach((label) => {
      expect(screen.getByRole('button', { name: label })).toBeTruthy();
    });
  });

  it('渲染耗时基线（粗粒度冒烟预算，非硬性性能契约）', () => {
    const commits: Commit[] = [];
    const onRender: ProfilerOnRenderCallback = (_id, phase, actualDuration) => {
      commits.push({ phase, actualDuration });
    };

    const utils = render(
      <Profiler id="target" onRender={onRender}>
        <SettingsNav activeSection="global" onNavigate={vi.fn()} />
      </Profiler>,
    );
    // 8 个静态导航项的 mount 不应超过 50ms（jsdom 下实测远低于此）。
    // 预算刻意宽松：只用于拦截「量级级」的退化，而不是精确的性能断言。
    expect(commits[0].actualDuration).toBeLessThan(50);

    utils.unmount();
  });
});
