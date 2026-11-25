/**
 * 券商通用参数格式规则（前端实现服务端注册表声明的 `timeFormat` / `hhmmIntRule`）。
 * 字段名映射已迁移到 `GET /api/broker-param-fields`（057 DL-16 收尾 / 220）。
 */
export function hhmmToEmsxInt(value: string): number | null {
  if (!value) return null;
  const parts = value.split(':');
  if (parts.length !== 2) return null;
  const hh = parseInt(parts[0], 10);
  const mm = parseInt(parts[1], 10);
  if (isNaN(hh) || isNaN(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
  return hh * 100 + mm;
}

const TIME_PATTERN = /^([01]\d|2[0-3]):[0-5]\d:[0-5]\d$/;

/** HH:MM:SS 校验；空串视为未填写（通过）。 */
export function isValidTimeFormat(value: string): boolean {
  return value === '' || TIME_PATTERN.test(value);
}