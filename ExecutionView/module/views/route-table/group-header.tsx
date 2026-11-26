/** Secondary group header (A14/229). Extracted verbatim from RouteTable.tsx. */

import { ChevronDown, ChevronRight } from 'lucide-react';
import { ROUTE_GROUP_BY_LABELS, type RouteGroupByValue } from '@execution/lib';
import type { Route } from '@execution/types';
import { TOTAL_COLS } from './helpers';

interface SubGroupHeaderProps {
  primaryKey: string;
  subKey: string;
  subRoutes: Route[];
  isExpanded: boolean;
  secondary: RouteGroupByValue;
  onToggle: (key: string) => void;
}

export const SubGroupHeader = ({
  primaryKey,
  subKey,
  subRoutes,
  isExpanded,
  secondary,
  onToggle,
}: SubGroupHeaderProps) => (
  <tr
    className="bg-secondary/20 border-y border-border/40 cursor-pointer select-none"
    onClick={() => onToggle(`${primaryKey}-${subKey}`)}
  >
    <td colSpan={TOTAL_COLS} className="px-8 py-1 text-xs">
      <div className="flex items-center gap-1.5">
        {isExpanded
          ? <ChevronDown className="h-3 w-3 text-muted-foreground" />
          : <ChevronRight className="h-3 w-3 text-muted-foreground" />}
        <span className="text-muted-foreground">{ROUTE_GROUP_BY_LABELS[secondary]}:</span>
        <span className="font-medium">{subKey}</span>
        <span className="text-muted-foreground/60">({subRoutes.length})</span>
      </div>
    </td>
  </tr>
);
