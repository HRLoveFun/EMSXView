export const BROKER_VOLUME_CAP_FIELD: Record<string, Record<string, string>> = {
  'EQ-BARCLAY': {
    'AuctionEU': 'Max Vol %',
    'TClose-EU': '',
    'VWAP-EU': 'Max % Volume',
  },
  'EQ-BNP': {
    'VWAP': 'Max % Vol',
    'TWAP': 'Max % Vol',
  },
  'EQ-CITI': {
    'VWAP': 'Max % Volume',
    'TWAP': 'Max % Volume',
    'IS': 'Max % Volume',
  },
  'EQ-CLSA': {
    'VWAP_ADP': 'Max%Volume',
    'VolinLine': 'Max%Volume',
    'DMA': '',
    'Float': 'Max%Volume',
  },
  'EQ-CLSA-EU': {
    'VWAP_ADP': 'Max%Volume',
    'VolinLine': 'Max%Volume',
    'DMA': '',
    'Float': 'Max%Volume',
  },
  'EQ-DAIWA': {
    'VWAP': 'Max % Volume',
    'TWAP': 'Max % Volume',
  },
  'EQ-GS': {
    'VWAP': 'VolumeLimit%',
    'TWAP': 'VolumeLimit%',
    'IS': 'VolumeLimit%',
  },
  'EQ-HSBC': {
    'VWAP.': 'Max % Vol',
    'TWAP.': 'Max % Vol',
  },
  'EQ-INSTNET': {
    'VWAP': 'MaxRate%',
    'TWAP': 'MaxRate%',
    'IS': 'MaxRate%',
  },
  'EQ-JPM': {
    'VWAP': 'Max % Vol.',
    'TWAP': 'Max % Vol.',
    'IS': 'Max % Vol.',
  },
  'EQ-MACQ': {
    'VWAP': 'Max % Volume',
    'TWAP': 'Max % Volume',
    'CLOSEPLUS': 'CloseMax%Vol',
  },
  'EQ-MIZUHO': {
    'VWAP': 'MaxVol%',
    'VWAP AI': 'MaxVol%',
    'TWAP': 'MaxVol%',
  },
  'EQ-ML': {
    'VWAP': 'Max % Vol',
    'TWAP': 'Max % Vol',
  },
  'EQ-MS': {
    'VWAP': '% Volume',
    'TWAP': '% Volume',
    'TARGETPOV': '% Volume',
    'CLOSE': 'Max%Vol',
    'SORT DMA': '',
    'PEGGED': '',
    'TARGETCLO': '',
  },
  'EQ-NOMURA': {
    'VWAP': 'MaxRate%',
    'TWAP': 'MaxRate%',
  },
  'EQ-SEB': {
    'VWAP': 'Particp Rate',
    'TWAP': 'Particp Rate',
  },
  'EQ-UBS': {
    'VWAP': 'Max % Vol',
    'TWAP': 'Max % Vol',
    'IS': 'Max % Vol',
  },
};

export function getVolumeCapField(broker: string, strategy: string): string {
  const brokerMap = BROKER_VOLUME_CAP_FIELD[broker];
  if (!brokerMap) return '';
  if (strategy) {
    const norm = (s: string) => s.toUpperCase().replace(/[^A-Z0-9]/g, '');
    const normStrategy = norm(strategy);
    const match = Object.keys(brokerMap).find(k => norm(k) === normStrategy);
    if (match) return brokerMap[match];
  }
  return brokerMap['*'] ?? '';
}

export const VOLUME_CAP_MULTIPLIER = 18;
