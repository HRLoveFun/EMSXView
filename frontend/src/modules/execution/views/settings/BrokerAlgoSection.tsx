import { useState, useEffect } from 'react';
import {
  Database, ChevronRight, ChevronDown, Clock, RefreshCw, CheckCircle2,
  AlertCircle, Plus, Save, Trash2, FileJson, AlertTriangle,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { useBrokerAlgorithms } from '@execution/hooks/use-broker-algorithms';
import type { StrategyParameter } from '@execution/types';
import { StrategyDataManagerDialog } from '@execution/components/strategy-data-manager-dialog';

interface TreeNode {
  id: string;
  name: string;
  type: 'broker' | 'algorithm';
  children?: TreeNode[];
}

export function BrokerAlgoSection() {
  const {
    configs,
    isLoading,
    isRefreshing,
    lastUpdated,
    error,
    refreshData,
    getStrategiesForBroker,
    getParametersForStrategy,
  } = useBrokerAlgorithms();

  const [treeData, setTreeData] = useState<TreeNode[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<{ broker: string; strategy: string } | null>(null);
  const [algorithmParams, setAlgorithmParams] = useState<StrategyParameter[]>([]);
  const [isLoadingParams, setIsLoadingParams] = useState(false);
  const [hasParamChanges, setHasParamChanges] = useState(false);
  const [isAddAlgoDialogOpen, setIsAddAlgoDialogOpen] = useState(false);
  const [newAlgoName, setNewAlgoName] = useState('');
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);
  const [isStrategyManagerOpen, setIsStrategyManagerOpen] = useState(false);

  useEffect(() => {
    if (configs.length === 0) {
      setTreeData([]);
      return;
    }
    setTreeData(configs.map(config => ({
      id: `broker::${config.broker}`,
      name: config.broker,
      type: 'broker' as const,
      children: getStrategiesForBroker(config.broker).map(strategy => ({
        id: `algo::${config.broker}::${strategy.name}`,
        name: strategy.name,
        type: 'algorithm' as const,
      })),
    })));
  }, [configs, getStrategiesForBroker]);

  const toggleNode = (nodeId: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  };

  const handleSelectAlgorithm = (broker: string, strategy: string) => {
    setSelectedAlgorithm({ broker, strategy });
    setIsLoadingParams(true);
    setHasParamChanges(false);
    setAlgorithmParams(getParametersForStrategy(broker, strategy));
    setIsLoadingParams(false);
  };

  const handleParamChange = (index: number, newValue: string) => {
    setAlgorithmParams(prev => {
      const next = [...prev];
      next[index] = { ...next[index], stringValue: newValue };
      return next;
    });
    setHasParamChanges(true);
  };

  const handleSaveParamChanges = () => setHasParamChanges(false);

  const formatLastUpdated = (date: Date | null): string => {
    if (!date) return 'Never';
    return date.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  const renderTreeNode = (node: TreeNode, level: number = 0) => {
    const isExpanded = expandedNodes.has(node.id);
    const algoMatch = node.id.startsWith('algo::') ? node.id.split('::') : null;
    return (
      <div key={node.id}>
        <div
          className={`flex items-center gap-1 py-1.5 px-2 hover:bg-muted/50 cursor-pointer rounded-sm ${node.type === 'algorithm' && selectedAlgorithm?.strategy === node.name && algoMatch && selectedAlgorithm?.broker === algoMatch[1] ? 'bg-primary/10' : ''}`}
          style={{ paddingLeft: `${level * 16 + 12}px` }}
          onClick={() => {
            if (node.children) toggleNode(node.id);
            if (node.type === 'algorithm' && algoMatch) handleSelectAlgorithm(algoMatch[1], algoMatch[2]);
          }}
        >
          {node.children ? (isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />) : <span className="w-4" />}
          <span className="text-sm">{node.name}</span>
        </div>
        {isExpanded && node.children && <div>{node.children.map(child => renderTreeNode(child, level + 1))}</div>}
      </div>
    );
  };

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5 text-primary" />
              <CardTitle className="text-base">Broker Algorithm Configuration</CardTitle>
            </div>
            <Button variant="outline" size="sm" onClick={() => setIsStrategyManagerOpen(true)}>
              <FileJson className="h-4 w-4 mr-2" />Strategy Data Manager
            </Button>
          </div>
          <CardDescription>Configure algorithm parameters by exchange, broker, and strategy</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between mb-4 px-3 py-2 bg-muted/30 rounded-md">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Last updated:</span>
                <span className="font-medium">{formatLastUpdated(lastUpdated)}</span>
              </div>
              {isRefreshing ? (
                <div className="flex items-center gap-2 text-blue-500">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Refreshing...</span>
                </div>
              ) : lastUpdated ? (
                <div className="flex items-center gap-2 text-green-500">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Up to date</span>
                </div>
              ) : null}
            </div>
            <Button variant="outline" size="sm" onClick={refreshData} disabled={isRefreshing}>
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />Refresh Now
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="mb-4">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div className="border rounded-md">
              <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Broker / Algorithm</span>
                <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => setIsAddAlgoDialogOpen(true)} disabled={!selectedAlgorithm}>
                  <Plus className="h-3 w-3 mr-1" />Add
                </Button>
              </div>
              <ScrollArea className="h-[300px]">
                {isLoading ? (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground">
                    <RefreshCw className="h-6 w-6 animate-spin" />
                    <span className="text-xs">Loading broker algorithms...</span>
                  </div>
                ) : treeData.length === 0 ? (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm px-4 text-center">
                    <div><p>No broker algorithms available</p><p className="text-xs mt-1">Click "Refresh Now" to load from Bloomberg API</p></div>
                  </div>
                ) : (
                  <div className="py-2">{treeData.map(node => renderTreeNode(node))}</div>
                )}
              </ScrollArea>
            </div>

            <div className="border rounded-md">
              <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Algorithm Parameters</span>
                {selectedAlgorithm && (
                  <div className="flex items-center gap-1">
                    {hasParamChanges && (
                      <Button variant="default" size="sm" className="h-6 text-xs" onClick={handleSaveParamChanges}>
                        <Save className="h-3 w-3 mr-1" />Save
                      </Button>
                    )}
                    <Button variant="ghost" size="sm" className="h-6 text-xs text-destructive hover:text-destructive" onClick={() => setIsDeleteConfirmOpen(true)}>
                      <Trash2 className="h-3 w-3 mr-1" />Delete
                    </Button>
                  </div>
                )}
              </div>
              <ScrollArea className="h-[300px]">
                {selectedAlgorithm ? (
                  <div className="p-3">
                    <div className="mb-3"><Badge variant="outline" className="text-xs">{selectedAlgorithm.broker} / {selectedAlgorithm.strategy}</Badge></div>
                    {isLoadingParams ? (
                      <div className="text-center text-muted-foreground py-8">Loading...</div>
                    ) : algorithmParams.length > 0 ? (
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-xs text-muted-foreground border-b">
                            <th className="text-left py-1 font-semibold">Name</th>
                            <th className="text-left py-1 font-semibold">Type</th>
                            <th className="text-left py-1 font-semibold">Value</th>
                            <th className="text-left py-1 font-semibold">Description</th>
                          </tr>
                        </thead>
                        <tbody>
                          {algorithmParams.map((param, idx) => (
                            <tr key={param.fieldName} className="border-b border-border/50">
                              <td className="py-2 text-xs">{param.fieldName}</td>
                              <td className="py-2 text-xs"><Badge variant="outline" className="text-[10px]">{param.dataType}</Badge></td>
                              <td className="py-2"><Input value={param.stringValue} onChange={(e) => handleParamChange(idx, e.target.value)} disabled={param.disable === 'Y'} className="h-7 text-xs" placeholder={param.disable === 'Y' ? 'Disabled' : 'Enter value'} /></td>
                              <td className="py-2 text-xs text-muted-foreground max-w-[150px] truncate" title={param.description}>{param.description}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <div className="text-center text-muted-foreground py-8">No parameters available for this strategy</div>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">Select an algorithm to view parameters</div>
                )}
              </ScrollArea>
            </div>
          </div>
        </CardContent>
      </Card>

      <Dialog open={isAddAlgoDialogOpen} onOpenChange={setIsAddAlgoDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Plus className="h-5 w-5" />Add New Algorithm</DialogTitle>
            <DialogDescription>Create a new algorithm for {selectedAlgorithm?.broker}</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Algorithm Name</Label>
              <Input value={newAlgoName} onChange={(e) => setNewAlgoName(e.target.value)} placeholder="e.g., VWAP, TWAP, Arrival Price" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAddAlgoDialogOpen(false)}>Cancel</Button>
            <Button onClick={() => { if (newAlgoName.trim()) { setIsAddAlgoDialogOpen(false); setNewAlgoName(''); } }} disabled={!newAlgoName.trim()}>Create Algorithm</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={isDeleteConfirmOpen} onOpenChange={setIsDeleteConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive"><AlertTriangle className="h-5 w-5" />Delete Algorithm</DialogTitle>
            <DialogDescription>Are you sure you want to delete <strong>{selectedAlgorithm?.strategy}</strong> for {selectedAlgorithm?.broker}? This action cannot be undone.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDeleteConfirmOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => { setIsDeleteConfirmOpen(false); setSelectedAlgorithm(null); setAlgorithmParams([]); }}>
              <Trash2 className="h-4 w-4 mr-2" />Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <StrategyDataManagerDialog open={isStrategyManagerOpen} onOpenChange={setIsStrategyManagerOpen} configs={configs} />
    </>
  );
}
