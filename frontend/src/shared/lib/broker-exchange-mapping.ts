/**
 * Broker ↔ Exchange Mapping（跨模块共享只读配置）
 *
 * 硬编码的 broker → 支持交易所/交易状态映射。
 * 数据源：ExecutionView 的 "Market Broker Mapping"（Settings）与
 * CostView Configure 的 "Report Exchanges" 交易所清单。
 *
 * 单一真相源：各模块不得复制本清单，一律从本文件导入。
 */

export const EXCHANGE_FOR_BROKER: Record<string, { exchange: string; active: boolean }[]> = {
  'EQ-BARCLAY': [ // Replaced BBC
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'LI', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'PW', active: false },
    { exchange: 'RM', active: false },
    { exchange: 'SJ', active: false },
    { exchange: 'SM', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: false },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: false }
  ],
  'EQ-BHP': [
    { exchange: 'IT', active: false }
  ],
  'EQ-BNP': [ // Replaced BNP
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IJ', active: false },
    { exchange: 'IM', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'LI', active: false },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-ML': [ // Replaced BOA
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'IT', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'PW', active: true },
    { exchange: 'SJ', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-ML-BR': [ // Replaced BOA
    { exchange: 'BZ', active: true }
  ],
  'EQ-CITI': [ // Replaced CIT
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'BZ', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'IJ', active: false },
    { exchange: 'IM', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'IT', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
    { exchange: 'LI', active: false },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'MM', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: false },
    { exchange: 'PL', active: true },
    { exchange: 'PW', active: true },
    { exchange: 'RM', active: false },
    { exchange: 'SJ', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-CLSA': [ // Replaced CLS
    { exchange: 'IJ', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
  ],
  'EQ-CLSA-EU': [ // Replaced CLS
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'SM', active: true }
  ],



  'EQ-DAIWA': [ // Replaced DAI
    { exchange: 'JP', active: true }
  ],
  'EQ-GS': [ // Replaced GOL
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'LI', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-HSBC': [ // Replaced HSB
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'IT', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
    { exchange: 'LI', active: false },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'PW', active: true },
    { exchange: 'RM', active: false },
    { exchange: 'SJ', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: false },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-INSTNET': [ // Replaced IST
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GA', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'LI', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'NZ', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-JPM': [ // Replaced JPM
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'BZ', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: false },
    { exchange: 'IJ', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
    { exchange: 'LI', active: false },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'MM', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'RM', active: true },
    { exchange: 'SJ', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-MIZUHO': [ // Replaced MFG
    { exchange: 'JP', active: true }
  ],
  'EQ-MS': [ // Replaced MOR
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'BZ', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'KS', active: true },
    { exchange: 'LI', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'MM', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'RM', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ],
  'EQ-MACQ': [ // Replaced MQG
    { exchange: 'AU', active: true },
    { exchange: 'IJ', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'NZ', active: true }
  ],
  'EQ-NOMURA': [ // Replaced NOM
    { exchange: 'JP', active: true }
  ],
  'EQ-SEB': [ // Replaced SEB
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'SS', active: true }
  ],
  'EQ-TD': [ // Replaced TDB
    { exchange: 'CN', active: true },
    { exchange: 'US', active: true }
  ],
  'EQ-UBS': [ // Replaced UBS
    { exchange: 'AU', active: true },
    { exchange: 'AV', active: true },
    { exchange: 'BB', active: true },
    { exchange: 'BZ', active: true },
    { exchange: 'CN', active: true },
    { exchange: 'DC', active: true },
    { exchange: 'FH', active: true },
    { exchange: 'FP', active: true },
    { exchange: 'GR', active: true },
    { exchange: 'ID', active: true },
    { exchange: 'IJ', active: true },
    { exchange: 'IM', active: true },
    { exchange: 'IN', active: true },
    { exchange: 'JP', active: true },
    { exchange: 'LI', active: true },
    { exchange: 'LN', active: true },
    { exchange: 'MK', active: true },
    { exchange: 'MM', active: true },
    { exchange: 'NA', active: true },
    { exchange: 'NO', active: true },
    { exchange: 'PL', active: true },
    { exchange: 'PW', active: true },
    { exchange: 'SJ', active: true },
    { exchange: 'SM', active: true },
    { exchange: 'SP', active: true },
    { exchange: 'SS', active: true },
    { exchange: 'SW', active: true },
    { exchange: 'US', active: true },
    { exchange: 'VX', active: true }
  ]
};

/**
 * Convert EXCHANGE_FOR_BROKER into a market-centric SelectionMap.
 * Result: { exchange: { broker: active } }
 */
export function getBrokerExchangeMapping(): Record<string, Record<string, boolean>> {
  const result: Record<string, Record<string, boolean>> = {};
  for (const [broker, entries] of Object.entries(EXCHANGE_FOR_BROKER)) {
    for (const { exchange, active } of entries) {
      if (!result[exchange]) result[exchange] = {};
      result[exchange][broker] = active;
    }
  }
  return result;
}

/**
 * Report Exchanges 专有交易所（2026-08-25）
 * 仅出现在 CostView Configure → Report Exchanges 清单，**不进入**
 * Market Broker Mapping 授权表（不挂到任何 broker 下，`getBrokerExchangeMapping()`
 * 不包含它们）。C1 = 沪港通（行情代码映射 CH），HK = 香港。
 */
const REPORT_ONLY_EXCHANGES: readonly string[] = ['C1', 'HK'];

/** 全部交易所代码（Report Exchanges 下拉清单：Market Broker Mapping 全部市场 + Report 专有市场），按字母序排列 */
export const EXCHANGE_LIST: string[] = Array.from(
  new Set([
    ...Object.values(EXCHANGE_FOR_BROKER).flatMap((entries) => entries.map((e) => e.exchange)),
    ...REPORT_ONLY_EXCHANGES,
  ]),
).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
