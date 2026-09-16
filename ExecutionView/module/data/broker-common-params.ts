export function hhmmToEmsxInt(value: string): number | null {
  if (!value) return null;
  const parts = value.split(':');
  if (parts.length !== 2) return null;
  const hh = parseInt(parts[0], 10);
  const mm = parseInt(parts[1], 10);
  if (isNaN(hh) || isNaN(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) return null;
  return hh * 100 + mm;
}