import { useState, useEffect, useCallback } from 'react';
import {
  Plus, Pencil, Trash2, Play, Power, PowerOff, AlertTriangle,
  Loader2, GripVertical,
} from 'lucide-react';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { apiService } from '@/services/api';
import type {
  RoutePlan, RoutePlanAllocation, CreateRoutePlanRequest, UpdateRoutePlanRequest,
  SplitType, ActivationMode, MatchSide,
} from '@/types';

// ============================================================================
// Route Plan Manager
// ============================================================================

export function RoutePlanManager() {
  const [plans, setPlans] = useState<RoutePlan[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');
  const [editPlan, setEditPlan] = useState<RoutePlan | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [testResult, setTestResult] = useState<{ planId: number; matchCount: number } | null>(null);

  const loadPlans = useCallback(async () => {
    setIsLoading(true);
    setError('');
    const result = await apiService.listRoutePlans();
    if (result.success && result.data) {
      setPlans(result.data);
    } else {
      setError(result.error || 'Failed to load route plans');
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    loadPlans();
  }, [loadPlans]);

  const handleToggleEnabled = async (plan: RoutePlan) => {
    await apiService.updateRoutePlan(plan.id, { enabled: !plan.enabled });
    loadPlans();
  };

  const handleDelete = async (planId: number) => {
    if (!confirm('确认删除此路由方案？')) return;
    await apiService.deleteRoutePlan(planId);
    loadPlans();
  };

  const handleTestMatch = async (planId: number) => {
    const result = await apiService.testMatchRoutePlan(planId);
    if (result.success && result.data) {
      setTestResult({ planId, matchCount: result.data.matchCount });
      setTimeout(() => setTestResult(null), 5000);
    }
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">路由方案管理</h3>
          <p className="text-sm text-muted-foreground">
            预设路由方案模板，自动匹配订单并生成待确认的子订单
          </p>
        </div>
        <Button
          size="sm"
          onClick={() => { setEditPlan(null); setIsDialogOpen(true); }}
        >
          <Plus className="h-4 w-4 mr-1" />
          新建方案
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {plans.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          <p className="text-sm">暂无路由方案</p>
          <p className="text-xs mt-1">点击"新建方案"创建第一个路由方案</p>
        </div>
      ) : (
        <div className="rounded-md border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/50">
              <tr>
                <th className="text-left px-3 py-2 font-medium">名称</th>
                <th className="text-left px-3 py-2 font-medium">匹配条件</th>
                <th className="text-left px-3 py-2 font-medium">拆分方式</th>
                <th className="text-left px-3 py-2 font-medium">模式</th>
                <th className="text-left px-3 py-2 font-medium">状态</th>
                <th className="text-right px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {plans.map(plan => (
                <tr key={plan.id} className="border-b hover:bg-muted/30 transition-colors">
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{plan.name}</div>
                    {plan.description && (
                      <div className="text-xs text-muted-foreground truncate max-w-48">
                        {plan.description}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {plan.matchSymbol && <Badge variant="outline" className="text-xs">{plan.matchSymbol}</Badge>}
                      {plan.matchSide !== 'BOTH' && <Badge variant="secondary" className="text-xs">{plan.matchSide}</Badge>}
                      {plan.matchPortfolio && <Badge variant="outline" className="text-xs">{plan.matchPortfolio}</Badge>}
                      {plan.matchTrader && <Badge variant="outline" className="text-xs">{plan.matchTrader}</Badge>}
                      {!plan.matchSymbol && !plan.matchPortfolio && !plan.matchTrader && (
                        <span className="text-xs text-muted-foreground">全部</span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant="secondary" className="text-xs">
                      {plan.splitType === 'BROKER_SPLIT' ? 'Broker分配' :
                       plan.splitType === 'TIME_SCHEDULE' ? `时间拆分 (${plan.scheduleType || 'TWAP'})` :
                       plan.splitType === 'HYBRID' ? 'Broker+时间' : plan.splitType}
                    </Badge>
                    {plan.allocations.length > 0 && (
                      <div className="text-xs text-muted-foreground mt-0.5">
                        {plan.allocations.map(a => a.broker).join(', ')}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge variant={plan.activationMode === 'AUTO' ? 'default' : 'outline'} className="text-xs">
                      {plan.activationMode === 'AUTO' ? '自动' : '手动'}
                    </Badge>
                  </td>
                  <td className="px-3 py-2.5">
                    {testResult?.planId === plan.id ? (
                      <Badge variant="secondary" className="text-xs">
                        匹配 {testResult.matchCount} 单
                      </Badge>
                    ) : (
                      <Badge variant={plan.enabled ? 'default' : 'secondary'} className="text-xs">
                        {plan.enabled ? '启用' : '禁用'}
                      </Badge>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-0.5">
                      <Button
                        variant="ghost" size="icon" className="h-7 w-7"
                        title="测试匹配"
                        onClick={() => handleTestMatch(plan.id)}
                      >
                        <Play className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost" size="icon" className="h-7 w-7"
                        title={plan.enabled ? '禁用' : '启用'}
                        onClick={() => handleToggleEnabled(plan)}
                      >
                        {plan.enabled ? <PowerOff className="h-3.5 w-3.5" /> : <Power className="h-3.5 w-3.5" />}
                      </Button>
                      <Button
                        variant="ghost" size="icon" className="h-7 w-7"
                        title="编辑"
                        onClick={() => { setEditPlan(plan); setIsDialogOpen(true); }}
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost" size="icon" className="h-7 w-7 text-destructive"
                        title="删除"
                        onClick={() => handleDelete(plan.id)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <RoutePlanDialog
        open={isDialogOpen}
        onOpenChange={setIsDialogOpen}
        editPlan={editPlan}
        onSaved={loadPlans}
      />
    </div>
  );
}

// ============================================================================
// Route Plan Create/Edit Dialog
// ============================================================================

interface RoutePlanDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  editPlan: RoutePlan | null;
  onSaved: () => void;
}

const splitTypeOptions: { value: SplitType; label: string }[] = [
  { value: 'BROKER_SPLIT', label: 'Broker 分配' },
  { value: 'TIME_SCHEDULE', label: '时间拆分' },
  { value: 'HYBRID', label: 'Broker + 时间 (混合)' },
];

const scheduleTypeOptions = [
  { value: 'TWAP', label: 'TWAP' },
  { value: 'VWAP', label: 'VWAP' },
  { value: 'POV', label: 'POV' },
];

function RoutePlanDialog({ open, onOpenChange, editPlan, onSaved }: RoutePlanDialogProps) {
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [matchMarket, setMatchMarket] = useState('');
  const [matchSymbol, setMatchSymbol] = useState('');
  const [matchSide, setMatchSide] = useState<MatchSide>('BOTH');
  const [matchPortfolio, setMatchPortfolio] = useState('');
  const [matchTrader, setMatchTrader] = useState('');
  const [matchExchange, setMatchExchange] = useState('');
  const [matchCurrency, setMatchCurrency] = useState('');
  const [activationMode, setActivationMode] = useState<ActivationMode>('MANUAL');
  const [splitType, setSplitType] = useState<SplitType>('BROKER_SPLIT');
  const [scheduleType, setScheduleType] = useState('TWAP');
  const [numSlices, setNumSlices] = useState(10);
  const [defaultEndTimeLocal, setDefaultEndTimeLocal] = useState('16:00');
  const [allocations, setAllocations] = useState<RoutePlanAllocation[]>([]);
  const [marketOptions, setMarketOptions] = useState<string[]>([]);
  const [availableBrokers, setAvailableBrokers] = useState<string[]>([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  // Reset form on open/edit
  useEffect(() => {
    if (!open) return;
    if (editPlan) {
      setName(editPlan.name);
      setDescription(editPlan.description || '');
      setMatchMarket(editPlan.matchMarket || '');
      setMatchSymbol(editPlan.matchSymbol || '');
      setMatchSide(editPlan.matchSide);
      setMatchPortfolio(editPlan.matchPortfolio || '');
      setMatchTrader(editPlan.matchTrader || '');
      setMatchExchange(editPlan.matchExchange || '');
      setMatchCurrency(editPlan.matchCurrency || '');
      setActivationMode(editPlan.activationMode);
      setSplitType(editPlan.splitType);
      setScheduleType(editPlan.scheduleType || 'TWAP');
      setNumSlices(editPlan.numSlices || 10);
      setDefaultEndTimeLocal(editPlan.defaultEndTimeLocal || '16:00');
      setAllocations(editPlan.allocations || []);
    } else {
      setName('');
      setDescription('');
      setMatchMarket('');
      setMatchSymbol('');
      setMatchSide('BOTH');
      setMatchPortfolio('');
      setMatchTrader('');
      setMatchExchange('');
      setMatchCurrency('');
      setActivationMode('MANUAL');
      setSplitType('BROKER_SPLIT');
      setScheduleType('TWAP');
      setNumSlices(10);
      setDefaultEndTimeLocal('16:00');
      setAllocations([]);
    }
    setError('');
  }, [open, editPlan]);

  // Fetch markets & brokers from Market Broker Mapping API
  useEffect(() => {
    if (!open) return;
    apiService.getMarketBrokerMapping().then(result => {
      if (!result.success || !result.data) return;
      const { rosters } = result.data;
      setMarketOptions(Object.keys(rosters || {}).sort());
      if (matchMarket) {
        setAvailableBrokers(rosters?.[matchMarket] || []);
      }
    }).catch(() => { /* silently ignore */ });
  }, [open]);

  useEffect(() => {
    if (!matchMarket) { setAvailableBrokers([]); return; }
    // Re-fetch brokers when market changes (the promise above may not have settled yet)
    apiService.getMarketBrokerMapping().then(result => {
      if (result.success && result.data) {
        setAvailableBrokers(result.data.rosters?.[matchMarket] || []);
      }
    }).catch(() => setAvailableBrokers([]));
  }, [matchMarket]);

  const addAllocation = () => {
    setAllocations(prev => [...prev, {
      broker: '',
      allocationType: 'PERCENTAGE',
      allocationValue: 0,
      sortOrder: prev.length,
    }]);
  };

  const removeAllocation = (idx: number) => {
    setAllocations(prev => prev.filter((_, i) => i !== idx));
  };

  const updateAllocation = (idx: number, field: Partial<RoutePlanAllocation>) => {
    setAllocations(prev => prev.map((a, i) => i === idx ? { ...a, ...field } : a));
  };

  const handleSubmit = async () => {
    if (!name.trim()) { setError('请输入方案名称'); return; }
    if (!matchMarket.trim()) { setError('请选择市场'); return; }

    if (splitType === 'BROKER_SPLIT' || splitType === 'HYBRID') {
      if (allocations.length === 0) { setError('请至少添加一个 Broker 分配'); return; }
      const pctSum = allocations
        .filter(a => a.allocationType === 'PERCENTAGE')
        .reduce((s, a) => s + a.allocationValue, 0);
      if (Math.abs(pctSum - 100) > 0.01) {
        setError(`百分比分配总和为 ${pctSum.toFixed(1)}%，应为 100%`);
        return;
      }
    }

    setError('');
    setIsSubmitting(true);

    try {
      if (editPlan) {
        const req: UpdateRoutePlanRequest = {
          name, description: description || null,
          matchMarket: matchMarket || undefined,
          matchSymbol: matchSymbol || null,
          matchSide,
          matchPortfolio: matchPortfolio || null,
          matchTrader: matchTrader || null,
          matchExchange: matchExchange || null,
          matchCurrency: matchCurrency || null,
          activationMode,
          splitType,
          scheduleType: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? scheduleType : null,
          numSlices: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? numSlices : null,
          defaultEndTimeLocal: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? defaultEndTimeLocal : null,
          allocations: (splitType === 'BROKER_SPLIT' || splitType === 'HYBRID') ? allocations : null,
        };
        await apiService.updateRoutePlan(editPlan.id, req);
      } else {
        const req: CreateRoutePlanRequest = {
          name, description: description || null,
          matchMarket: matchMarket.trim(),
          matchSymbol: matchSymbol || null,
          matchSide,
          matchPortfolio: matchPortfolio || null,
          matchTrader: matchTrader || null,
          matchExchange: matchExchange || null,
          matchCurrency: matchCurrency || null,
          activationMode,
          splitType,
          scheduleType: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? scheduleType : null,
          numSlices: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? numSlices : null,
          defaultEndTimeLocal: (splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID') ? defaultEndTimeLocal : null,
          allocations: (splitType === 'BROKER_SPLIT' || splitType === 'HYBRID') ? allocations : null,
        };
        await apiService.createRoutePlan(req);
      }
      onSaved();
      onOpenChange(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : '保存失败');
    } finally {
      setIsSubmitting(false);
    }
  };

  const needsTimeConfig = splitType === 'TIME_SCHEDULE' || splitType === 'HYBRID';
  const needsBrokerConfig = splitType === 'BROKER_SPLIT' || splitType === 'HYBRID';

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{editPlan ? '编辑路由方案' : '新建路由方案'}</DialogTitle>
          <DialogDescription>
            配置匹配条件和拆分策略，用于自动或手动生成子订单提案
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-4 py-4">
          {/* Basic info */}
          <div className="grid grid-cols-4 items-center gap-4">
            <Label className="text-right">名称 *</Label>
            <Input
              value={name}
              onChange={e => setName(e.target.value)}
              className="col-span-3"
              placeholder="例如：AAPL 多Broker分配"
            />
          </div>

          {/* Match criteria */}
          <div className="border-t pt-4 mt-2">
            <Label className="text-sm font-semibold mb-2 block">匹配条件（市场为必选）</Label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground">市场 *</Label>
                <Select value={matchMarket} onValueChange={v => setMatchMarket(v)}>
                  <SelectTrigger className="mt-1"><SelectValue placeholder="选择市场..." /></SelectTrigger>
                  <SelectContent>
                    {marketOptions.map(m => (
                      <SelectItem key={m} value={m}>{m}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">货币（可选）</Label>
                <Input
                  value={matchCurrency}
                  onChange={e => setMatchCurrency(e.target.value.toUpperCase())}
                  placeholder="如 USD, JPY"
                  className="mt-1"
                  maxLength={8}
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">股票代码 (支持 * 通配符)</Label>
                <Input
                  value={matchSymbol}
                  onChange={e => setMatchSymbol(e.target.value)}
                  placeholder="如 AAPL, 700.*"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">方向</Label>
                <Select value={matchSide} onValueChange={v => setMatchSide(v as MatchSide)}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="BOTH">买入+卖出</SelectItem>
                    <SelectItem value="BUY">仅买入</SelectItem>
                    <SelectItem value="SELL">仅卖出</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">组合</Label>
                <Input
                  value={matchPortfolio}
                  onChange={e => setMatchPortfolio(e.target.value)}
                  placeholder="如 ASIA_EQ"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">交易员</Label>
                <Input
                  value={matchTrader}
                  onChange={e => setMatchTrader(e.target.value)}
                  placeholder="交易员名"
                  className="mt-1"
                />
              </div>
            </div>
          </div>

          {/* Split strategy */}
          <div className="border-t pt-4 mt-2">
            <Label className="text-sm font-semibold mb-2 block">拆分策略</Label>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs text-muted-foreground">拆分方式</Label>
                <Select value={splitType} onValueChange={v => setSplitType(v as SplitType)}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    {splitTypeOptions.map(opt => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <Label className="text-xs text-muted-foreground">激活模式</Label>
                <Select value={activationMode} onValueChange={v => setActivationMode(v as ActivationMode)}>
                  <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="MANUAL">手动触发</SelectItem>
                    <SelectItem value="AUTO">自动匹配</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Time config */}
          {needsTimeConfig && (
            <div className="border-t pt-4 mt-2">
              <Label className="text-sm font-semibold mb-2 block">时间拆分参数</Label>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <Label className="text-xs text-muted-foreground">算法</Label>
                  <Select value={scheduleType} onValueChange={setScheduleType}>
                    <SelectTrigger className="mt-1"><SelectValue /></SelectTrigger>
                    <SelectContent>
                      {scheduleTypeOptions.map(opt => (
                        <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">切片数</Label>
                  <Input
                    type="number"
                    value={numSlices}
                    onChange={e => setNumSlices(Number(e.target.value))}
                    className="mt-1"
                    min={1} max={100}
                  />
                </div>
                <div>
                  <Label className="text-xs text-muted-foreground">结束时间</Label>
                  <Input
                    value={defaultEndTimeLocal}
                    onChange={e => setDefaultEndTimeLocal(e.target.value)}
                    className="mt-1"
                    placeholder="16:00"
                  />
                </div>
              </div>
            </div>
          )}

          {/* Broker allocations */}
          {needsBrokerConfig && (
            <div className="border-t pt-4 mt-2">
              <div className="flex items-center justify-between mb-2">
                <Label className="text-sm font-semibold">Broker 分配</Label>
                <div className="flex items-center gap-2">
                  {availableBrokers.length > 0 && (
                    <span className="text-xs text-muted-foreground">
                      {availableBrokers.length} brokers 可用
                    </span>
                  )}
                  <Button variant="outline" size="sm" onClick={addAllocation}>
                    <Plus className="h-3 w-3 mr-1" /> 添加
                  </Button>
                </div>
              </div>
              {allocations.length === 0 ? (
                <p className="text-xs text-muted-foreground">
                  {matchMarket ? '点击"添加"按钮添加 Broker 分配' : '请先选择市场以加载可用 Broker 列表'}
                </p>
              ) : (
                <div className="space-y-2">
                  {allocations.map((alloc, idx) => (
                    <div key={idx} className="flex items-center gap-2 p-2 rounded-md border bg-muted/20">
                      <GripVertical className="h-4 w-4 text-muted-foreground shrink-0" />
                      <div className="relative w-24">
                        <Input
                          value={alloc.broker}
                          onChange={e => updateAllocation(idx, { broker: e.target.value.toUpperCase() })}
                          placeholder="Broker"
                          className="w-24"
                          list={`broker-suggestions-${idx}`}
                        />
                        {availableBrokers.length > 0 && (
                          <datalist id={`broker-suggestions-${idx}`}>
                            {availableBrokers.map(b => <option key={b} value={b} />)}
                          </datalist>
                        )}
                      </div>
                      <Select
                        value={alloc.allocationType}
                        onValueChange={v => updateAllocation(idx, { allocationType: v as 'PERCENTAGE' | 'FIXED' })}
                      >
                        <SelectTrigger className="w-20"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="PERCENTAGE">%</SelectItem>
                          <SelectItem value="FIXED">股</SelectItem>
                        </SelectContent>
                      </Select>
                      <Input
                        type="number"
                        value={alloc.allocationValue}
                        onChange={e => updateAllocation(idx, { allocationValue: Number(e.target.value) })}
                        className="w-20"
                        min={0}
                        step={alloc.allocationType === 'PERCENTAGE' ? 1 : 100}
                      />
                      <Button
                        variant="ghost" size="icon" className="h-7 w-7 text-destructive shrink-0"
                        onClick={() => removeAllocation(idx)}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                  {allocations.filter(a => a.allocationType === 'PERCENTAGE').length > 0 && (
                    <p className="text-xs text-muted-foreground text-right">
                      百分比合计: {allocations.filter(a => a.allocationType === 'PERCENTAGE').reduce((s, a) => s + a.allocationValue, 0).toFixed(1)}%
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {error && (
            <Alert variant="destructive">
              <AlertTriangle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isSubmitting}>
            取消
          </Button>
          <Button onClick={handleSubmit} disabled={isSubmitting}>
            {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
            {editPlan ? '保存' : '创建'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
