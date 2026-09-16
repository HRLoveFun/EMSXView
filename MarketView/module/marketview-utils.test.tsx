import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import {
  fmtCompact,
  fmtNumber,
  fmtPercent,
  getSeverityText,
  getSeverityTone,
  renderSeverityBadge,
} from './marketview-utils';

describe('MarketView format helpers', () => {
  it('formats numbers with fixed digits and dashes for missing values', () => {
    expect(fmtNumber(189.25, 2)).toBe('189.25');
    expect(fmtNumber(null)).toBe('—');
    expect(fmtNumber(undefined)).toBe('—');
  });

  it('formats compact volume notation', () => {
    expect(fmtCompact(105000000)).toBe('105M');
    expect(fmtCompact(null)).toBe('—');
  });

  it('formats percentages with a percent suffix', () => {
    expect(fmtPercent(22.4, 1)).toBe('22.4%');
    expect(fmtPercent(null, 1)).toBe('—');
  });
});

describe('MarketView severity helpers', () => {
  it('maps severity levels to readable text', () => {
    expect(getSeverityText('critical')).toBe('Critical');
    expect(getSeverityText('warning')).toBe('Warning');
    expect(getSeverityText('normal')).toBe('Normal');
    expect(getSeverityText('none')).toBe('N/A');
  });

  it('assigns distinct tones per severity', () => {
    expect(getSeverityTone('critical')).toContain('red');
    expect(getSeverityTone('warning')).toContain('amber');
    expect(getSeverityTone('normal')).toContain('emerald');
    expect(getSeverityTone('none')).toContain('muted');
  });

  it('renders a labelled severity badge', () => {
    render(renderSeverityBadge('Liquidity', 'critical'));
    expect(screen.getByText('Liquidity: Critical')).toBeInTheDocument();
  });
});
