import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { BatchOperationPanel } from './BatchOperationPanel';

describe('BatchOperationPanel', () => {
  it('renders nothing when no orders are selected', () => {
    const { container } = render(
      <BatchOperationPanel
        selectedOrderIds={[]}
        onBatchUpdate={vi.fn()}
        onClearSelection={vi.fn()}
        isLoading={false}
      />,
    );
    expect(container.innerHTML).toBe('');
  });

  it('shows order count when orders are selected', () => {
    render(
      <BatchOperationPanel
        selectedOrderIds={['ORD1', 'ORD2']}
        onBatchUpdate={vi.fn()}
        onClearSelection={vi.fn()}
        isLoading={false}
      />,
    );

    expect(screen.getByText(/2 orders? selected/i)).toBeInTheDocument();
    expect(screen.getByText('Batch Modify')).toBeInTheDocument();
    expect(screen.getByText('Clear selection')).toBeInTheDocument();
  });

  it('calls onClearSelection when clear button is clicked', async () => {
    const onClearSelection = vi.fn();
    const user = userEvent.setup();

    render(
      <BatchOperationPanel
        selectedOrderIds={['ORD1']}
        onBatchUpdate={vi.fn()}
        onClearSelection={onClearSelection}
        isLoading={false}
      />,
    );

    await user.click(screen.getByText('Clear selection'));
    expect(onClearSelection).toHaveBeenCalledTimes(1);
  });

  it('opens batch modify dialog and shows form fields', async () => {
    const user = userEvent.setup();

    render(
      <BatchOperationPanel
        selectedOrderIds={['ORD1', 'ORD2']}
        onBatchUpdate={vi.fn()}
        onClearSelection={vi.fn()}
        isLoading={false}
      />,
    );

    await user.click(screen.getByText('Batch Modify'));

    expect(screen.getByText('Field to Modify')).toBeInTheDocument();
    expect(screen.getByText('New Value')).toBeInTheDocument();
  });
});
