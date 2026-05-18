import { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Check, X as XIcon, Loader2, AlertTriangle, Clock, Send, EyeOff,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Checkbox } from '@/components/ui/checkbox';
import { apiService } from '@execution/services/execution-api';
import type {
  SubOrderProposal, BatchOperationItemResult, BatchOperationResult,
} from '@/types';

// ============================================================================
// Sub-order Review Panel
// ============================================================================

interface SubOrderReviewPanelProps {
  currentTrader?: string;
  onRefresh?: () => void;
}

export function SubOrderReviewPanel({ currentTrader, onRefresh }: SubOrderReviewPanelProps) {
  const [proposals, setProposals] = useState<SubOrderProposal[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [submittingIds, setSubmittingIds] = useState<Set<number>>(new Set());
  const [batchResult, setBatchResult] = useState<BatchOperationResult | null>(null);

  const loadProposals = useCallback(async () => {
    setIsLoading(true);
    setError('');
    const result = await apiService.listSubOrderProposals('PENDING_CONFIRM', currentTrader);
    if (result.success && result.data) {
      setProposals(result.data);
    } else {
      setError(result.error || 'Failed to load proposals');
    }
    setIsLoading(false);
  }, [currentTrader]);

  useEffect(() => {
    loadProposals();
  }, [loadProposals]);

  // Auto-poll every 15 seconds
  useEffect(() => {
    const interval = setInterval(loadProposals, 15000);
    return () => clearInterval(interval);
  }, [loadProposals]);

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === proposals.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(proposals.map(p => p.id)));
    }
  };

  const handleConfirmOne = async (proposalId: number) => {
    setSubmittingIds(prev => new Set(prev).add(proposalId));
    const result = await apiService.confirmProposal(proposalId);
    if (result.success) {
      setProposals(prev => prev.filter(p => p.id !== proposalId));
      setSelectedIds(prev => { const n = new Set(prev); n.delete(proposalId); return n; });
    }
    setSubmittingIds(prev => { const n = new Set(prev); n.delete(proposalId); return n; });
    onRefresh?.();
  };

  const handleRejectOne = async (proposalId: number) => {
    setSubmittingIds(prev => new Set(prev).add(proposalId));
    await apiService.rejectProposal(proposalId);
    setProposals(prev => prev.filter(p => p.id !== proposalId));
    setSubmittingIds(prev => { const n = new Set(prev); n.delete(proposalId); return n; });
  };

  const handleBatchConfirm = async () => {
    if (selectedIds.size === 0) return;
    setBatchResult(null);
    const onItem = (item: BatchOperationItemResult) => {
      setBatchResult(prev => prev ? {
        ...prev,
        items: [...prev.items, item],
        succeeded: item.status === 'SUCCESS' ? prev.succeeded + 1 : prev.succeeded,
        blocked: item.status === 'BLOCKED' ? prev.blocked + 1 : prev.blocked,
        failed: item.status === 'FAILED' ? prev.failed + 1 : prev.failed,
      } : {
        total: selectedIds.size,
        succeeded: item.status === 'SUCCESS' ? 1 : 0,
        blocked: item.status === 'BLOCKED' ? 1 : 0,
        failed: item.status === 'FAILED' ? 1 : 0,
        items: [item],
      });
    };
    const onSummary = (_summary: BatchOperationResult) => {
      loadProposals();
      setSelectedIds(new Set());
      onRefresh?.();
    };
    await apiService.batchConfirmProposals({
      proposalIds: [...selectedIds],
    }, onItem, onSummary);
  };

  // Group by parent order
  const grouped = useMemo(() => {
    const groups: Record<string, SubOrderProposal[]> = {};
    for (const p of proposals) {
      const key = p.parentSymbol || p.parentOrderId;
      if (!groups[key]) groups[key] = [];
      groups[key].push(p);
    }
    return groups;
  }, [proposals]);

  if (isLoading && proposals.length === 0) {
    return (
      <div className="flex items-center justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h4 className="text-sm font-semibold">Pending Sub-Orders</h4>
          {proposals.length > 0 && (
            <Badge variant="default" className="text-xs">{proposals.length}</Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          {selectedIds.size > 0 && (
            <Button size="sm" onClick={handleBatchConfirm}>
              <Send className="h-3.5 w-3.5 mr-1" />
              Batch Confirm ({selectedIds.size})
            </Button>
          )}
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={loadProposals} title="Refresh">
            <Loader2 className={`h-3.5 w-3.5 ${isLoading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {error && (
        <Alert variant="destructive" className="py-2">
          <AlertTriangle className="h-3.5 w-3.5" />
          <AlertDescription className="text-xs">{error}</AlertDescription>
        </Alert>
      )}

      {batchResult && (
        <Alert variant={batchResult.failed > 0 ? 'destructive' : 'default'} className="py-2">
          <AlertDescription className="text-xs">
            Batch submit complete: {batchResult.succeeded} succeeded
            {batchResult.blocked > 0 && `, ${batchResult.blocked} blocked`}
            {batchResult.failed > 0 && `, ${batchResult.failed} failed`}
          </AlertDescription>
        </Alert>
      )}

      {proposals.length === 0 ? (
        <div className="rounded-md border border-dashed p-6 text-center text-muted-foreground">
          <EyeOff className="h-5 w-5 mx-auto mb-1 opacity-50" />
          <p className="text-xs">No pending sub-orders</p>
          <p className="text-xs mt-0.5">New orders matching route plans will appear here</p>
        </div>
      ) : (
        <div className="space-y-2">
          {Object.entries(grouped).map(([symbol, groupProposals]) => (
            <div key={symbol} className="rounded-md border">
              <div className="flex items-center gap-2 px-3 py-2 bg-muted/30 border-b">
                <Checkbox
                  checked={groupProposals.every(p => selectedIds.has(p.id))}
                  onCheckedChange={() => {
                    const allSelected = groupProposals.every(p => selectedIds.has(p.id));
                    setSelectedIds(prev => {
                      const next = new Set(prev);
                      for (const p of groupProposals) {
                        if (allSelected) next.delete(p.id);
                        else next.add(p.id);
                      }
                      return next;
                    });
                  }}
                />
                <span className="text-xs font-medium">{symbol}</span>
                <Badge variant="outline" className="text-xs">
                  {groupProposals[0]?.parentSide || ''}
                </Badge>
                <span className="text-xs text-muted-foreground ml-auto">
                  Total {groupProposals.reduce((s, p) => s + p.quantity, 0).toLocaleString()} shares
                </span>
              </div>
              <div className="divide-y">
                {groupProposals.map(p => (
                  <div key={p.id} className="flex items-center gap-3 px-3 py-2 text-xs hover:bg-muted/20 transition-colors">
                    <Checkbox
                      checked={selectedIds.has(p.id)}
                      onCheckedChange={() => toggleSelect(p.id)}
                    />
                    <Badge variant="secondary" className="text-xs w-16 justify-center">
                      {p.broker}
                    </Badge>
                    <span className="w-16 text-right tabular-nums">
                      {p.quantity.toLocaleString()}
                    </span>
                    <span className="text-muted-foreground w-12">
                      {p.orderType || 'LMT'}
                    </span>
                    {p.limitPrice && (
                      <span className="text-muted-foreground">{p.limitPrice.toFixed(2)}</span>
                    )}
                    {p.sliceIndex != null && (
                      <Badge variant="outline" className="text-xs">
                        <Clock className="h-2.5 w-2.5 mr-0.5" />
                        #{p.sliceIndex + 1}
                      </Badge>
                    )}
                    <div className="flex items-center gap-0.5 ml-auto">
                      <Button
                        variant="ghost" size="icon" className="h-6 w-6 text-green-600"
                        title="Confirm & Submit"
                        onClick={() => handleConfirmOne(p.id)}
                        disabled={submittingIds.has(p.id)}
                      >
                        {submittingIds.has(p.id) ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Check className="h-3 w-3" />
                        )}
                      </Button>
                      <Button
                        variant="ghost" size="icon" className="h-6 w-6 text-destructive"
                        title="Reject"
                        onClick={() => handleRejectOne(p.id)}
                        disabled={submittingIds.has(p.id)}
                      >
                        <XIcon className="h-3 w-3" />
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}