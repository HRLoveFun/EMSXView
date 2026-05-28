import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { OrderStatusBadge } from './order-status-badge';

describe('OrderStatusBadge', () => {
  it('renders the status text', () => {
    render(<OrderStatusBadge status="WORKING" />);
    expect(screen.getByText('WORKING')).toBeInTheDocument();
  });

  it('renders FILLED status', () => {
    render(<OrderStatusBadge status="FILLED" />);
    expect(screen.getByText('FILLED')).toBeInTheDocument();
  });

  it('renders REJECTED status', () => {
    render(<OrderStatusBadge status="REJECTED" />);
    expect(screen.getByText('REJECTED')).toBeInTheDocument();
  });

  it('renders PENDING_CANCEL status', () => {
    render(<OrderStatusBadge status="PENDING_CANCEL" />);
    expect(screen.getByText('PENDING_CANCEL')).toBeInTheDocument();
  });
});
