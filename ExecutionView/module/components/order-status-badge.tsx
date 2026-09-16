import type { OrderStatus } from '@execution/types';
import { Badge } from '@/components/ui/badge';

const STATUS_STYLE: Record<OrderStatus, { variant: 'default' | 'secondary' | 'destructive' | 'outline'; className?: string }> = {
  NEW:            { variant: 'outline' },
  ASSIGN:         { variant: 'outline', className: 'border-cyan-500 text-cyan-600' },
  WORKING:        { variant: 'default', className: 'bg-blue-500/90 hover:bg-blue-600' },
  PARTIAL:        { variant: 'default', className: 'bg-amber-500/90 hover:bg-amber-600' },
  FILLED:         { variant: 'default', className: 'bg-emerald-500/90 hover:bg-emerald-600' },
  CANCELLED:      { variant: 'secondary', className: 'border border-dashed border-muted-foreground/40 italic' },
  COMPLETED:      { variant: 'outline', className: 'border-emerald-700 text-emerald-700 dark:text-emerald-400 font-semibold' },
  QUEUED:         { variant: 'default', className: 'bg-purple-500/90 hover:bg-purple-600' },
  SUSPENDED:      { variant: 'default', className: 'bg-orange-500/90 hover:bg-orange-600' },
  PENDING_CANCEL: { variant: 'destructive', className: 'bg-red-600 ring-2 ring-red-300 animate-pulse' },
  REJECTED:       { variant: 'destructive', className: 'bg-red-700/90' },
  SENT:           { variant: 'default', className: 'bg-sky-500/90 hover:bg-sky-600' },
};

interface OrderStatusBadgeProps {
  status: OrderStatus;
}

export function OrderStatusBadge({ status }: OrderStatusBadgeProps) {
  const style = STATUS_STYLE[status] ?? { variant: 'outline' as const };
  return (
    <Badge variant={style.variant} className={`text-[10px] px-1.5 py-0 leading-4 ${style.className ?? ''}`}>
      {status}
    </Badge>
  );
}
