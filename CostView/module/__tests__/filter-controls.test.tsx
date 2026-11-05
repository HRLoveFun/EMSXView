import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SegmentedField } from '../components/SegmentedField';
import { SearchableSelect } from '../components/SearchableSelect';
import { SavedViewBar } from '../components/SavedViewBar';
import { deleteView, loadSavedViews, saveView } from '../lib/saved-views';
import { loadRecentValues, recordRecentValue } from '../lib/recent-values';

beforeEach(() => {
  window.localStorage.clear();
});

describe('SegmentedField', () => {
  const options = [
    { value: 'BUY', label: 'BUY' },
    { value: 'SELL', label: 'SELL' },
  ];

  it('单选：点击即替换', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SegmentedField label="方向" options={options} value="BUY" onChange={onChange} />);

    await user.click(screen.getByRole('button', { name: 'SELL' }));
    expect(onChange).toHaveBeenCalledWith('SELL');
    expect(screen.getByRole('button', { name: 'BUY' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('多选：再次点击取消，clearValue 清空', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const withClear = [{ value: '', label: '全部' }, ...options];
    render(
      <SegmentedField
        label="方向"
        options={withClear}
        value={['BUY']}
        onChange={onChange}
        multiple
        clearValue=""
      />,
    );

    await user.click(screen.getByRole('button', { name: 'BUY' }));
    expect(onChange).toHaveBeenCalledWith([]);

    await user.click(screen.getByRole('button', { name: '全部' }));
    expect(onChange).toHaveBeenCalledWith([]);
  });
});

describe('SearchableSelect', () => {
  const options = ['Alice Chen', 'Bob Li', 'Carol Wang'];

  it('打开后输入过滤，↑↓ + Enter 选中', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect label="交易员" options={options} value={[]} onChange={onChange} />,
    );

    await user.click(screen.getByRole('button', { name: '交易员' }));
    await user.type(screen.getByRole('combobox'), 'a');
    await user.keyboard('{ArrowDown}{Enter}');

    expect(onChange).toHaveBeenCalledWith(['Alice Chen']);
  });

  it('多选不关闭，已选 chip 可单独移除', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect label="交易员" options={options} value={['Alice Chen', 'Bob Li']} onChange={onChange} />,
    );

    await user.click(screen.getByRole('button', { name: '移除 Alice Chen' }));
    expect(onChange).toHaveBeenCalledWith(['Bob Li']);
  });

  it('Backspace 在空查询时删除最后一个已选值', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect label="交易员" options={options} value={['Alice Chen', 'Bob Li']} onChange={onChange} />,
    );

    await user.click(screen.getByRole('button', { name: '交易员' }));
    await user.keyboard('{Backspace}');
    expect(onChange).toHaveBeenCalledWith(['Alice Chen']);
  });

  it('单选模式选中后关闭并替换', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect
        label="Broker"
        options={options}
        value={[]}
        onChange={onChange}
        multiple={false}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Broker' }));
    await user.click(screen.getByRole('option', { name: /Bob Li/ }));

    expect(onChange).toHaveBeenCalledWith(['Bob Li']);
  });

  it('allowCustom 下输入恰好等于已有选项时 Enter 直接选中', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect
        label="标的"
        options={options}
        value={[]}
        onChange={onChange}
        allowCustom
      />,
    );

    await user.click(screen.getByRole('button', { name: '标的' }));
    await user.type(screen.getByRole('combobox'), 'Alice Chen');
    await user.keyboard('{Enter}');

    expect(onChange).toHaveBeenCalledWith(['Alice Chen']);
  });

  it('键盘光标按值定位：已选项跳到「已选」分组后再次 Enter 仍作用于同一项', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <SearchableSelect label="标的" options={['Alpha', 'Beta', 'Gamma']} value={[]} onChange={onChange} />,
    );

    await user.click(screen.getByRole('button', { name: '标的' }));
    await user.keyboard('{ArrowDown}{ArrowDown}{ArrowDown}{Enter}');
    expect(onChange).toHaveBeenLastCalledWith(['Gamma']);

    rerender(
      <SearchableSelect label="标的" options={['Alpha', 'Beta', 'Gamma']} value={['Gamma']} onChange={onChange} />,
    );
    await user.keyboard('{Enter}');
    expect(onChange).toHaveBeenLastCalledWith([]);
  });

  it('已选 chip 超过上限时折叠为 +N，避免上百个徽标撑高筛选栏', () => {
    render(
      <SearchableSelect
        label="标的"
        options={[]}
        value={['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']}
        onChange={vi.fn()}
      />,
    );

    expect(screen.getAllByRole('button', { name: /^移除 / })).toHaveLength(6);
    expect(screen.getByText('还有 2 项')).toBeInTheDocument();
  });

  it('allowCustom 可把未知输入添加为值', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <SearchableSelect
        label="标的"
        options={options}
        value={[]}
        onChange={onChange}
        allowCustom
      />,
    );

    await user.click(screen.getByRole('button', { name: '标的' }));
    await user.type(screen.getByRole('combobox'), 'ZZZ US Equity');
    await user.click(screen.getByRole('button', { name: /添加自定义/ }));

    expect(onChange).toHaveBeenCalledWith(['ZZZ US Equity']);
  });
});

describe('SavedViewBar', () => {
  it('输入名称后回调 onSave', async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <SavedViewBar views={[]} activeId={null} onApply={vi.fn()} onSave={onSave} onDelete={vi.fn()} />,
    );

    await user.click(screen.getByRole('button', { name: /保存当前筛选/ }));
    await user.type(screen.getByPlaceholderText('视图名称，如 每日复盘'), '每日复盘');
    await user.click(screen.getByRole('button', { name: '保存视图' }));

    expect(onSave).toHaveBeenCalledWith('每日复盘');
  });
});

describe('saved-views store', () => {
  it('保存、按名称覆盖、删除', () => {
    saveView('test', '每日复盘', { traders: ['Alice'] });
    saveView('test', '算法对比', { traders: ['Bob'] });
    expect(loadSavedViews<{ traders: string[] }>('test')).toHaveLength(2);

    saveView('test', '每日复盘', { traders: ['Carol'] });
    const views = loadSavedViews<{ traders: string[] }>('test');
    expect(views).toHaveLength(2);
    expect(views.find((view) => view.name === '每日复盘')?.state.traders).toEqual(['Carol']);

    deleteView('test', views[0].id);
    expect(loadSavedViews('test')).toHaveLength(1);
  });

  it('损坏数据回退为空列表', () => {
    window.localStorage.setItem('emsx_costview_saved_views_v1:test', '{not-json');
    expect(loadSavedViews('test')).toEqual([]);
  });
});

describe('recent-values store', () => {
  it('按最近使用排序并去重', () => {
    recordRecentValue('trader.traders', 'Alice');
    recordRecentValue('trader.traders', 'Bob');
    recordRecentValue('trader.traders', 'Alice');
    expect(loadRecentValues('trader.traders')).toEqual(['Alice', 'Bob']);
  });
});
