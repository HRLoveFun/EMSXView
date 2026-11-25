/**
 * Broker/strategy configuration types.
 *
 * P3-SRP: Extracted from types/index.ts.
 */

export interface BrokerStrategyField {
  fieldName: string;
  disable: string;
  stringValue: string;
}

export interface BrokerStrategiesResponse {
  broker: string;
  assetClass: string;
  strategies: string[];
}

export interface BrokerStrategyInfoResponse {
  broker: string;
  strategy: string;
  assetClass: string;
  fields: BrokerStrategyField[];
}

export interface StrategyParameter {
  fieldName: string;
  stringValue: string;
  disable: string;
  order?: number;
  dataType: 'string' | 'number' | 'boolean';
  description: string;
}

export interface StrategyConfig {
  name: string;
  parameters: StrategyParameter[];
}

export interface BrokerAlgorithmConfig {
  broker: string;
  assetClass?: string;
  strategies: StrategyConfig[];
}

/** 起止时间字段名（券商默认或券商×策略覆盖）。 */
export interface TimeFieldNames {
  start: string;
  end: string;
}

/** 券商参数字段注册表（GET /api/broker-param-fields，057 DL-16 收尾）。 */
export interface BrokerParamFields {
  version: string;
  timeFields: Record<string, TimeFieldNames>;
  timeFieldOverrides: Record<string, Record<string, TimeFieldNames>>;
  volumeCapFields: Record<string, Record<string, string>>;
  volumeCapMultiplier: number;
  integerCapBrokers: string[];
  timeFormat: string;
  hhmmIntRule: string;
}
