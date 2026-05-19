import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MultiSelectFilterPopover } from './MultiSelectFilterPopover';

describe('MultiSelectFilterPopover', () => {
  const options = ['WORKING', 'FILLED', 'CANCELLED'];

  it('renders filter button', () => {
    render(<MultiSelectFilterPopover label="status" options={options} selected={[]} onChange={() => {}} />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('shows "No status available" when options is empty', async () => {
    const user = userEvent.setup();
    render(<MultiSelectFilterPopover label="status" options={[]} selected={[]} onChange={() => {}} />);

    await user.click(screen.getByRole('button'));
    expect(screen.getByText('No status available')).toBeInTheDocument();
  });

  it('calls onChange with selected option when checkbox is clicked', async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();

    render(<MultiSelectFilterPopover label="status" options={options} selected={[]} onChange={onChange} />);

    await user.click(screen.getByRole('button'));

    const checkbox = screen.getByLabelText('WORKING');
    await user.click(checkbox);

    expect(onChange).toHaveBeenCalledWith(['WORKING']);
  });

  it('shows Include/Exclude toggle when onModeChange is provided', async () => {
    const user = userEvent.setup();

    render(
      <MultiSelectFilterPopover
        label="status"
        options={options}
        selected={[]}
        onChange={() => {}}
        mode="include"
        onModeChange={() => {}}
      />,
    );

    await user.click(screen.getByRole('button'));
    expect(screen.getByText('Include')).toBeInTheDocument();
    expect(screen.getByText('Exclude')).toBeInTheDocument();
  });
});
