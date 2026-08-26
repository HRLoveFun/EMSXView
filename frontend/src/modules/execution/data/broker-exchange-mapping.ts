/**
 * Broker ↔ Exchange Mapping（兼容入口）
 *
 * 硬编码映射已迁移至共享契约层 `@shared/lib/broker-exchange-mapping`，
 * 本文件仅作 re-export，保持 `@execution/data/broker-exchange-mapping`
 * 既有导入路径不变。新增使用方请直接从 shared 导入。
 */

export { EXCHANGE_FOR_BROKER, getBrokerExchangeMapping, EXCHANGE_LIST } from '@shared/lib/broker-exchange-mapping';
