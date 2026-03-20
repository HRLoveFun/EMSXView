import { useState } from 'react';
import { MoreHorizontal, X, Edit3, Settings, Lock } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Route } from '@/types';

// Route statuses that allow modification
const MODIFIABLE_STATUSES = ['SENT', 'WORKING', 'PARTFILL', 'QUEUED', 'HOLD'];

interface RouteActionMenuProps {
  route: Route;
  currentTrader: string;
  onCancel: (route: Route) => void;
  onModifyAmount: (route: Route) => void;
  onModifyType: (route: Route) => void;
  onModifyLimitPrice: (route: Route) => void;
  onBrokerStrategy: (route: Route) => void;
}

export function RouteActionMenu({
  route,
  currentTrader,
  onCancel,
  onModifyAmount,
  onModifyType,
  onModifyLimitPrice,
  onBrokerStrategy,
}: RouteActionMenuProps) {
  const [open, setOpen] = useState(false);

  const statusAllowsModify = MODIFIABLE_STATUSES.includes(route.status);
  // Trader name check: empty means not yet detected — allow access; otherwise must match
  const isOwnedByTerminal = !currentTrader || !route.trader || route.trader === currentTrader;
  const canModify = statusAllowsModify && isOwnedByTerminal;

  // If not owned by terminal, show a lock icon with tooltip
  if (!isOwnedByTerminal) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0 cursor-not-allowed opacity-40">
            <Lock className="h-3.5 w-3.5" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">
          <p className="text-xs">Owned by {route.trader} — cannot modify</p>
        </TooltipContent>
      </Tooltip>
    );
  }

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
          <MoreHorizontal className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuItem
          onClick={() => {
            onCancel(route);
            setOpen(false);
          }}
          disabled={!canModify}
          className="text-destructive focus:text-destructive"
        >
          <X className="mr-2 h-4 w-4" />
          Cancel Route
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() => {
            onModifyAmount(route);
            setOpen(false);
          }}
          disabled={!canModify}
        >
          <Edit3 className="mr-2 h-4 w-4" />
          Modify Quantity
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => {
            onModifyType(route);
            setOpen(false);
          }}
          disabled={!canModify}
        >
          <Edit3 className="mr-2 h-4 w-4" />
          Modify Order Type
        </DropdownMenuItem>

        <DropdownMenuItem
          onClick={() => {
            onModifyLimitPrice(route);
            setOpen(false);
          }}
          disabled={!canModify || route.orderType === 'MKT'}
        >
          <Edit3 className="mr-2 h-4 w-4" />
          Modify Limit Price
        </DropdownMenuItem>

        <DropdownMenuSeparator />

        <DropdownMenuItem
          onClick={() => {
            onBrokerStrategy(route);
            setOpen(false);
          }}
          disabled={!canModify}
        >
          <Settings className="mr-2 h-4 w-4" />
          Broker / Strategy
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
