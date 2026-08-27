interface TimeFieldNames {
  start: string;
  end: string;
}

export const BROKER_TIME_FIELDS: Record<string, TimeFieldNames> = {
  'EQ-BARCLAY': { start: 'StartTime', end: 'EndTime' },
  'EQ-MS': { start: 'Start Time', end: 'End Time' },
  'EQ-CLSA': { start: 'Start Time', end: 'End Time' },
  'EQ-CLSA-EU': { start: 'Start Time', end: 'End Time' },
  'EQ-UBS': { start: 'StartTime', end: 'EndTime' },
  'EQ-JPM': { start: 'Start Time', end: 'End Time' },
  'EQ-CITI': { start: 'StartTime', end: 'EndTime' },
  'EQ-GS': { start: 'StartTime', end: 'EndTime' },
  'EQ-ML': { start: 'Start Time', end: 'End Time' },
  'EQ-ML-BR': { start: 'Start Time', end: 'End Time' },
  'EQ-BNP': { start: 'Start Time', end: 'End Time' },
  'EQ-HSBC': { start: 'Start Time', end: 'End Time' },
  'EQ-TD': { start: 'StartTime', end: 'EndTime' },
  'EQ-MIZUHO': { start: 'Start Time', end: 'End Time' },
  'EQ-NOMURA': { start: 'StartTime', end: 'EndTime' },
  'EQ-INSTNET': { start: 'StartTime', end: 'EndTime' },
  'EQ-MACQ': { start: 'Start Time', end: 'End Time' },
  'EQ-DAIWA': { start: 'Start Time', end: 'End Time' },
  'EQ-SG': { start: 'Start Time', end: 'End Time' },
  'EQ-SEB': { start: 'Start Time', end: 'End Time' },
  'EQ-ABCI': { start: 'Start Time', end: 'End Time' },
};

export const BROKER_STRATEGY_TIME_OVERRIDES: Record<string, Record<string, TimeFieldNames>> = {
  'EQ-MACQ': {
    'CLOSEPLUS': { start: 'ContStrtTime', end: 'ContEndTime' },
  },
};

export function getStartTimeField(broker: string, _strategy: string): string {
  const override = BROKER_STRATEGY_TIME_OVERRIDES[broker]?.[_strategy];
  if (override) return override.start;
  return BROKER_TIME_FIELDS[broker]?.start ?? '';
}

export function getEndTimeField(broker: string, _strategy: string): string {
  const override = BROKER_STRATEGY_TIME_OVERRIDES[broker]?.[_strategy];
  if (override) return override.end;
  return BROKER_TIME_FIELDS[broker]?.end ?? '';
}

const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/;

export function isValidTimeFormat(value: string): boolean {
  return value === '' || TIME_PATTERN.test(value);
}