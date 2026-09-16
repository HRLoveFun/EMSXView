import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { TextFilterPopover } from './TextFilterPopover';

describe('TextFilterPopover', () => {
  it('renders filter button', () => {
    render(<TextFilterPopover value="" onChange={() => {}} placeholder="Filter..." />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('calls onChange on each keystroke', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<TextFilterPopover value="" onChange={onChange} placeholder="Filter ticker..." />);

    await user.click(screen.getByRole('button'));
    const input = screen.getByPlaceholderText('Filter ticker...');
    await user.type(input, 'A');

    expect(onChange).toHaveBeenCalledWith('A');
  });

  it('shows clear button when value is non-empty', () => {
    render(<TextFilterPopover value="AAPL" onChange={() => {}} placeholder="Filter..." />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });
});
