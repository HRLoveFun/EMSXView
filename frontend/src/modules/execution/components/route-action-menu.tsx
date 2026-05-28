import { useState } from 'react';
import { MoreHorizontal, X, Edit3, Lock, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import type { Route } from '@execution/types'

// Route statuses that allow modification
const MODIFIABLE_STATUSES = ['SENT', 'WORKING', 'PARTFILLED', 'PARTFILL', 'QUEUED', 'HOLD'];
// Transient Cancel/Replace states — modifications are temporarily blocked
// but this is a ~200ms transition, not a true terminal state.
const REPLACING_STATUSES = ['CXLRPRQ', 'CXLREP'];

interface RouteActionMenuProps {
  route: Route;
  currentTrader: string;
  onCancel: (route: Route) => void;
  onModify: (route: Route) => void;
}

export function RouteActionMenu({
  route,
  currentTrader,
  onCancel,
  onModify,
}: RouteActionMenuProps) {
  const [open, setOpen] = useState(false);

  const statusAllowsModify = MODIFIABLE_STATUSES.includes(route.status);
  const isReplacing = REPLACING_STATUSES.includes(route.status);
  const isOwnedByTerminal = !currentTrader || !route.trader || route.trader === currentTrader;
  const canModify = statusAllowsModify && isOwnedByTerminal;

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

  if (isReplacing) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <Button variant="ghost" size="sm" className="h-6 w-6 p-0 cursor-wait opacity-60">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          </Button>
        </TooltipTrigger>
        <TooltipContent side="left">
          <p className="text-xs">Replacing in progress — actions will be available in a moment</p>
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
      <DropdownMenuContent align="end" className="w-40">
        <DropdownMenuItem
          onClick={() => { onModify(route); setOpen(false); }}
          disabled={!canModify}
        >
          <Edit3 className="mr-2 h-4 w-4" />
          Modify Route
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onClick={() => { onCancel(route); setOpen(false); }}
          disabled={!canModify}
          className="text-destructive focus:text-destructive"
        >
          <X className="mr-2 h-4 w-4" />
          Cancel Route
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}