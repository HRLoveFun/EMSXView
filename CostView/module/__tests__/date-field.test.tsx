import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { DateField } from '../components/DateField';

describe('DateField 日期选择器', () => {
  // jsdom 没有实现 showPicker：按「浏览器支持 showPicker」渲染（否则组件会收起自定义按钮）
  beforeEach(() => {
    HTMLInputElement.prototype.showPicker = vi.fn();
  });

  afterEach(() => {
    delete (HTMLInputElement.prototype as Partial<HTMLInputElement>).showPicker;
  });

  it('点击输入框任意位置显式呼出原生日期选择器', async () => {
    const user = userEvent.setup();
    const showPicker = vi.fn();
    const { container } = render(<DateField label="起始日期" value="" onChange={vi.fn()} />);
    const input = container.querySelector('input[type="date"]') as HTMLInputElement;
    input.showPicker = showPicker;

    await user.click(input);

    expect(showPicker).toHaveBeenCalledTimes(1);
  });

  it('点击右侧日历按钮同样呼出选择器', async () => {
    const user = userEvent.setup();
    const showPicker = vi.fn();
    const { container } = render(<DateField label="截止日期" value="" onChange={vi.fn()} />);
    const input = container.querySelector('input[type="date"]') as HTMLInputElement;
    input.showPicker = showPicker;

    await user.click(screen.getByRole('button', { name: '选择截止日期' }));

    expect(showPicker).toHaveBeenCalledTimes(1);
  });

  it('日期变化回传 YYYY-MM-DD', () => {
    const onChange = vi.fn();
    const { container } = render(<DateField label="起始日期" value="" onChange={onChange} />);
    const input = container.querySelector('input[type="date"]') as HTMLInputElement;

    fireEvent.change(input, { target: { value: '2026-08-01' } });

    expect(onChange).toHaveBeenCalledWith('2026-08-01');
  });
});
