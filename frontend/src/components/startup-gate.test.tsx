import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import { StartupGate } from './startup-gate';

// 仅校验「认证缺失」与「后端未就绪」在文案上可区分（不涉及真实取数）
const renderGate = (message?: string) =>
  render(
    <StartupGate
      phase="backend_starting"
      elapsedSeconds={10}
      message={message}
      httpReady={false}
      bloombergStatus="connecting"
      subscriptionsReady={false}
      onRetry={vi.fn()}
    />,
  );

describe('StartupGate', () => {
  it('认证失败时给出独立标题，不描述成启动故障', () => {
    renderGate('Backend requires authentication. 本地开发请在 backend/.env 设置 BYPASS_AUTH=true');

    expect(screen.getByText('Backend requires authentication')).toBeInTheDocument();
    expect(screen.queryByText('Startup chain error')).not.toBeInTheDocument();
  });

  it('普通等待仍显示后端启动中', () => {
    renderGate('Frontend is up, waiting for the backend HTTP service to respond.');

    expect(screen.getByText('Backend HTTP service is starting')).toBeInTheDocument();
  });
});
