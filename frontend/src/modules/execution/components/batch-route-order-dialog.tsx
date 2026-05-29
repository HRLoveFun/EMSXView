/**
 * BatchRouteOrderDialog — multi-broker batch routing (thin orchestrator).
 *
 * All state, logic, and derived computations live in useBatchRouteState().
 * Each UI section is extracted into its own sub-component under batch-route-order/.
 *
 * UX model (re-designed 2026-04-28):
 *   1. User picks N brokers from a checklist at the top of the dialog.
 *   2. For each selected broker the user picks a strategy and edits its
 *      strategy parameters once — the same params apply to every destination.
 *   3. Per-order quantities are equally split across the chosen brokers,
 *      lot-rounded down. The user can override per-destination qty inline.
 *   4. Order type and price are inherited per parent (no batch override).
 *
 * Backend contract: POST /api/orders/batch-route
 *   - dryRun=true  → ApiResponse<BatchOperationResult> (validation)
 *   - dryRun=false → NDJSON stream + summary
 *
 * Compliance (server-enforced, hard block):
 *   USD notional < 10K, USD notional > 49M, JP odd lot.
 */

import { GitBranch, AlertTriangle, Loader2 } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';

import { useBatchRouteState } from './batch-route-order/use-batch-route-state';
import { BrokerSelectionPanel } from './batch-route-order/broker-selection-panel';
import { BrokerStrategySection } from './batch-route-order/broker-strategy-section';
import { BatchRouteToolbar } from './batch-route-order/batch-route-toolbar';
import { QuickFillToolbar } from './batch-route-order/quick-fill-toolbar';
import { BrokerRatioBar } from './batch-route-order/broker-ratio-bar';
import { OrderAllocationTable } from './batch-route-order/order-allocation-table';
import { ResultFeedback } from './batch-route-order/result-feedback';
import { defaultStrategyFor } from './batch-route-order/utils';

import type { BatchRouteOrderDialogProps } from './batch-route-order/types';

export function BatchRouteOrderDialog({
  orders,
  routes,
  open,
  onOpenChange,
  onComplete,
}: BatchRouteOrderDialogProps) {
  const s = useBatchRouteState({ orders, routes, open, onOpenChange, onComplete });

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) s.close(); }}>
      <DialogContent className="sm:max-w-6xl max-h-[90vh] overflow-y-auto">
        {/* ── Header ─────────────────────────────────────────────── */}
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            {orders.length === 1
              ? `Route Order — ${orders[0]?.symbol ?? orders[0]?.id}`
              : `Batch Route — ${orders.length} orders`}
          </DialogTitle>
          <DialogDescription>
            Pick brokers, set each broker's algo + params, then review qty
            splits per order. Order type and price are inherited from each
            parent order. Each order's available capacity = remaining
            quantity − quantity already working at the broker.
            Compliance (USD &lt; 10K / &gt; 49M, JP odd lot) is enforced
            server-side.
          </DialogDescription>
        </DialogHeader>

        {/* ── Broker selection ──────────────────────────────────── */}
        <BrokerSelectionPanel
          visibleBrokers={s.visibleBrokers}
          selectedBrokers={s.selectedBrokers}
          editable={s.editable}
          toggleBroker={s.toggleBroker}
          strategiesFor={s.strategiesFor}
          defaultStrategyFor={defaultStrategyFor}
          onSelectAll={() => s.visibleBrokers.forEach(b => { if (!s.selectedBrokers.includes(b)) s.toggleBroker(b); })}
          onDeselectAll={() => s.selectedBrokers.forEach(b => s.toggleBroker(b))}
        />

        {/* ── Multi-market block ────────────────────────────────── */}
        {s.orderMarkets.length > 1 && (
          <Alert variant="destructive" className="py-2 text-xs">
            <AlertTriangle className="h-3 w-3" />
            <AlertDescription>
              Batch route cannot process orders from multiple markets simultaneously.
              Selected orders span: <strong>{s.orderMarkets.join(', ')}</strong>.
              Please select orders from a single market and route each market separately.
            </AlertDescription>
          </Alert>
        )}

        {/* ── Per-broker strategy + params ──────────────────────── */}
        <BrokerStrategySection
          selectedBrokers={s.selectedBrokers}
          brokerStrategies={s.brokerStrategies}
          strategiesFor={s.strategiesFor}
          setBrokerStrategy={s.setBrokerStrategy}
          registerParamsBuilder={s.registerParamsBuilder}
          registerFieldSetter={s.registerFieldSetter}
          paramsCacheRef={s.paramsCacheRef}
          cacheKey={s.cacheKey}
          editable={s.editable}
          defaultStrategyFor={defaultStrategyFor}
        />

        {/* ── TIF + notes + time ───────────────────────────────── */}
        <BatchRouteToolbar
          tif={s.tif}
          notes={s.notes}
          releaseTime={s.releaseTime}
          startTime={s.startTime}
          endTime={s.endTime}
          editable={s.editable}
          selectedBrokers={s.selectedBrokers}
          onTifChange={s.setTif}
          onNotesChange={s.setNotes}
          onReleaseTimeChange={s.setReleaseTime}
          onStartTimeChange={s.setStartTime}
          onEndTimeChange={s.setEndTime}
          onApplyTimeToAll={s.applyTimeToAll}
        />

        {/* ── Quick-fill toolbar ────────────────────────────────── */}
        <QuickFillToolbar
          editable={s.editable}
          selectedBrokers={s.selectedBrokers}
          selectedOrders={s.selectedOrders}
          customPct={s.customPct}
          onCustomPctChange={s.setCustomPct}
          onApplyPercentQty={s.applyPercentQty}
        />

        {/* ── Broker ratio bar ──────────────────────────────────── */}
        <BrokerRatioBar
          selectedBrokers={s.selectedBrokers}
          ratios={s.ratios}
          ratioSum={s.ratioSum}
          ratioTotalValid={s.ratioTotalValid}
          editable={s.editable}
          setRatioForBroker={s.setRatioForBroker}
          resetRatios={s.resetRatios}
          applyRatios={s.applyRatios}
        />

        {/* ── Order allocation table ────────────────────────────── */}
        <OrderAllocationTable
          orders={orders}
          rows={s.rows}
          selectedBrokers={s.selectedBrokers}
          editable={s.editable}
          phase={s.phase}
          ratios={s.ratios}
          effectiveRemainingOf={s.effectiveRemainingOf}
          pendingWorkingByOrder={s.pendingWorkingByOrder}
          isBrokerAllowedFor={s.isBrokerAllowedFor}
          patchRow={s.patchRow}
          patchAlloc={s.patchAlloc}
          applyPercentToBroker={s.applyPercentToBroker}
        />

        {/* ── Result feedback ───────────────────────────────────── */}
        <ResultFeedback
          phase={s.phase}
          error={s.error}
          progress={s.progress}
          summary={s.summary}
          totalDestinations={s.totalDestinations}
          blockedDetails={s.blockedDetails}
          failedDetails={s.failedDetails}
          warnDetails={s.warnDetails}
        />

        {/* ── Footer ─────────────────────────────────────────────── */}
        <DialogFooter>
          {s.phase === 'configure' && (
            <>
              <Button variant="outline" onClick={s.close}>Cancel</Button>
              <Button onClick={s.runValidation} disabled={!s.canValidate}>
                Validate ({s.totalDestinations} destination{s.totalDestinations === 1 ? '' : 's'})
              </Button>
            </>
          )}
          {s.phase === 'review' && (
            <>
              <Button variant="outline" onClick={() => s.setPhase('configure')}>Back</Button>
              <Button onClick={s.runSubmit} disabled={s.selectedOrders.length === 0}>
                Confirm &amp; Route {s.totalDestinations} destination{s.totalDestinations === 1 ? '' : 's'}
              </Button>
            </>
          )}
          {s.phase === 'submitting' && (
            <Button disabled><Loader2 className="mr-2 h-4 w-4 animate-spin" />Working…</Button>
          )}
          {s.phase === 'result' && <Button onClick={s.close}>Close</Button>}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
