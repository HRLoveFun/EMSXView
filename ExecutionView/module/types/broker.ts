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
