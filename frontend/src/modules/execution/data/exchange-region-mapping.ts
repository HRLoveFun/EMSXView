/**
 * Exchange code → Region mapping
 *
 * Used by Market Broker Mapping to group market rows by region.
 * Four groups: APAC, EMEA, EUR, NSA.
 *
 * Source: desk-defined mapping.
 */

export type Region = 'APAC' | 'EMEA' | 'EUR' | 'NSA';

/** Exchange code to region lookup */
export const EXCHANGE_REGION: Record<string, Region> = {
  // APAC — Asia-Pacific
  AU: 'APAC',
  IJ: 'APAC',
  IN: 'APAC',
  JP: 'APAC',
  KS: 'APAC',
  MK: 'APAC',
  NZ: 'APAC',
  SP: 'APAC',

  // EMEA — Europe, Middle East & Africa (non-EUR)
  DC: 'EMEA',
  IT: 'EMEA',
  LI: 'EMEA',
  LN: 'EMEA',
  NO: 'EMEA',
  PW: 'EMEA',
  RM: 'EMEA',
  SJ: 'EMEA',
  SS: 'EMEA',
  SW: 'EMEA',
  VX: 'EMEA',

  // EUR — Eurozone
  AV: 'EUR',
  BB: 'EUR',
  FH: 'EUR',
  FP: 'EUR',
  GA: 'EUR',
  GR: 'EUR',
  ID: 'EUR',
  IM: 'EUR',
  NA: 'EUR',
  PL: 'EUR',
  SM: 'EUR',

  // NSA — Americas
  BZ: 'NSA',
  CN: 'NSA',
  MM: 'NSA',
  US: 'NSA',
};

/** Display order for region groups */
export const REGION_ORDER: Region[] = ['APAC', 'EMEA', 'EUR', 'NSA'];

/** Human-readable labels for each region */
export const REGION_LABELS: Record<Region, string> = {
  APAC: 'Asia-Pacific (APAC)',
  EMEA: 'Europe, Middle East & Africa (EMEA)',
  EUR: 'Eurozone (EUR)',
  NSA: 'Americas (NSA)',
};