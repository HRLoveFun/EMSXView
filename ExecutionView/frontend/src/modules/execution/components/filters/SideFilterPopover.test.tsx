import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SideFilterPopover } from './SideFilterPopover';

describe('SideFilterPopover', () => {
  it('renders filter button', () => {
    render(<SideFilterPopover value="" onChange={() => {}} />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('calls onChange with BUY when Buy is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<SideFilterPopover value="" onChange={onChange} />);

    await user.click(screen.getByRole('button'));
    await user.click(screen.getByText('Buy'));

    expect(onChange).toHaveBeenCalledWith('BUY');
  });

  it('calls onChange with SELL when Sell is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<SideFilterPopover value="BUY" onChange={onChange} />);

    await user.click(screen.getByRole('button'));
    await user.click(screen.getByText('Sell'));

    expect(onChange).toHaveBeenCalledWith('SELL');
  });

  it('calls onChange with empty string when All is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<SideFilterPopover value="BUY" onChange={onChange} />);

    await user.click(screen.getByRole('button'));
    await user.click(screen.getByText('All'));

    expect(onChange).toHaveBeenCalledWith('');
  });
});
