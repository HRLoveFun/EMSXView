import { useState, useEffect, useCallback } from 'react';
import {
  Settings,
  Bell,
  Monitor,
  ChevronRight,
  ChevronDown,
  Database,
  Download,
  Upload,
  RefreshCw,
  Save,
  Plus,
  Trash2,
  AlertCircle,
  AlertTriangle,
  FileJson,
  CheckCircle2,
  Clock,
  SlidersHorizontal,
  Info,
  Building2,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Checkbox } from '@/components/ui/checkbox';
import { useBrokerAlgorithms } from '@/hooks/use-broker-algorithms';
import type { StrategyParameter } from '@/types';
import {
  CONDITION_DEFS,
  DEFAULT_CONDITIONS,
  type MonitorConditions,
  type ConditionConfig,
  type BoolConditionConfig,
  type ConditionId,
} from '@/lib/monitor-conditions';
import {
  getFileCacheStatus,
  clearFileCache,
  exportConfiguration,
  importConfiguration,
  getAvailableBrokersFromFile,
} from '@/services/strategy-data-service';
import { MarketBrokerMappingSection } from '@/components/market-broker-mapping-section';

// ─── Types ───────────────────────────────────────────────────────────────────
interface ParameterFrequency {
  parameterName: string;
  frequency: 'realtime' | '5s' | '30s' | '1m' | 'custom';
  customSeconds?: number;
  lastUpdated: Date;
}

interface TreeNode {
  id: string;
  name: string;
  type: 'exchange' | 'broker' | 'algorithm';
  children?: TreeNode[];
  isLoading?: boolean;
}

interface CacheStatus {
  initialized: boolean;
  strategiesCount: number;
  paramsCount: number;
  lastLoaded: string | null;
}

const FREQUENCY_OPTIONS = [
  { value: 'realtime', label: 'Real-time' },
  { value: '5s', label: '5 seconds' },
  { value: '30s', label: '30 seconds' },
  { value: '1m', label: '1 minute' },
  { value: 'custom', label: 'Custom' },
];

const DEFAULT_FREQUENCIES: ParameterFrequency[] = [
  { parameterName: 'Order Status', frequency: 'realtime', lastUpdated: new Date() },
  { parameterName: 'Fill Quantity', frequency: 'realtime', lastUpdated: new Date() },
  { parameterName: 'Market Price', frequency: '5s', lastUpdated: new Date() },
  { parameterName: 'VWAP', frequency: '30s', lastUpdated: new Date() },
  { parameterName: 'ADV 5D', frequency: '1m', lastUpdated: new Date() },
  { parameterName: 'FX Rate', frequency: '30s', lastUpdated: new Date() },
];

// ─── Components ──────────────────────────────────────────────────────────────

type SettingsSectionId =
  | 'global'
  | 'monitor-conditions'
  | 'broker-algo'
  | 'market-broker-mapping'
  | 'parameter-frequency'
  | 'data-manager'
  | 'about';

interface SettingsBoardProps {
  monitorConditions?: MonitorConditions;
  onMonitorConditionsChange?: (c: MonitorConditions) => void;
  initialSection?: SettingsSectionId;
}

export function SettingsBoard({
  monitorConditions,
  onMonitorConditionsChange,
  initialSection = 'global',
}: SettingsBoardProps = {}) {
  const [activeSection, setActiveSection] = useState<SettingsSectionId>(initialSection);
  useEffect(() => { setActiveSection(initialSection); }, [initialSection]);
  // Global settings state
  const [monitorAlertsEnabled, setMonitorAlertsEnabled] = useState(() => {
    return localStorage.getItem('emsx_monitor_alerts_enabled') !== 'false';
  });
  const [desktopNotificationsEnabled, setDesktopNotificationsEnabled] = useState(() => {
    return localStorage.getItem('emsx_desktop_notifications') === 'true';
  });

  // Broker algorithm state from hook
  const {
    configs,
    isLoading,
    isRefreshing,
    lastUpdated,
    error,
    refreshData,
    getExchanges,
    getBrokersForExchange,
    getStrategiesForBroker,
    getParametersForStrategy,
  } = useBrokerAlgorithms();

  // UI state
  const [treeData, setTreeData] = useState<TreeNode[]>([]);
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [selectedAlgorithm, setSelectedAlgorithm] = useState<{ broker: string; strategy: string } | null>(null);
  const [algorithmParams, setAlgorithmParams] = useState<StrategyParameter[]>([]);
  const [isLoadingParams, setIsLoadingParams] = useState(false);
  const [hasParamChanges, setHasParamChanges] = useState(false);
  const [isAddAlgoDialogOpen, setIsAddAlgoDialogOpen] = useState(false);
  const [newAlgoName, setNewAlgoName] = useState('');
  const [isDeleteConfirmOpen, setIsDeleteConfirmOpen] = useState(false);

  // Parameter frequency state
  const [frequencies, setFrequencies] = useState<ParameterFrequency[]>(DEFAULT_FREQUENCIES);
  const [hasFrequencyChanges, setHasFrequencyChanges] = useState(false);

  // Strategy Data Manager state
  const [isStrategyManagerOpen, setIsStrategyManagerOpen] = useState(false);
  const [fileStatus, setFileStatus] = useState<CacheStatus | null>(null);
  const [brokers, setBrokers] = useState<string[]>([]);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [strategyMessage, setStrategyMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isStrategyLoading, setIsStrategyLoading] = useState(false);

  // Persist global settings
  useEffect(() => {
    localStorage.setItem('emsx_monitor_alerts_enabled', String(monitorAlertsEnabled));
  }, [monitorAlertsEnabled]);

  useEffect(() => {
    localStorage.setItem('emsx_desktop_notifications', String(desktopNotificationsEnabled));
    if (desktopNotificationsEnabled && 'Notification' in window) {
      Notification.requestPermission();
    }
  }, [desktopNotificationsEnabled]);

  // Build tree data from configs
  useEffect(() => {
    if (configs.length === 0) {
      setTreeData([]);
      return;
    }

    const exchanges = getExchanges();
    const data: TreeNode[] = exchanges.map(exchange => ({
      id: `exchange::${exchange}`,
      name: exchange,
      type: 'exchange',
      children: getBrokersForExchange(exchange).map(broker => ({
        id: `broker::${exchange}::${broker}`,
        name: broker,
        type: 'broker',
        children: getStrategiesForBroker(broker).map(strategy => ({
          id: `algo::${exchange}::${broker}::${strategy.name}`,
          name: strategy.name,
          type: 'algorithm',
        })),
      })),
    }));

    setTreeData(data);
  }, [configs, getExchanges, getBrokersForExchange, getStrategiesForBroker]);

  // Load strategy data for manager
  const loadStrategyStatus = useCallback(async () => {
    setFileStatus(getFileCacheStatus());
    const brokerList = await getAvailableBrokersFromFile();
    setBrokers(brokerList);
  }, []);

  useEffect(() => {
    if (isStrategyManagerOpen) {
      loadStrategyStatus();
    }
  }, [isStrategyManagerOpen, loadStrategyStatus]);

  // Toggle tree node expansion
  const toggleNode = (nodeId: string) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  // Handle algorithm selection
  const handleSelectAlgorithm = (broker: string, strategy: string) => {
    setSelectedAlgorithm({ broker, strategy });
    setIsLoadingParams(true);
    setHasParamChanges(false);

    const params = getParametersForStrategy(broker, strategy);
    setAlgorithmParams(params);
    setIsLoadingParams(false);
  };

  // Handle parameter value change
  const handleParamChange = (index: number, newValue: string) => {
    setAlgorithmParams(prev => {
      const next = [...prev];
      next[index] = { ...next[index], stringValue: newValue };
      return next;
    });
    setHasParamChanges(true);
  };

  // Handle save parameter changes
  const handleSaveParamChanges = async () => {
    // TODO: Persist to backend API
    setHasParamChanges(false);
  };

  // Handle add algorithm
  const handleAddAlgorithm = () => {
    if (!newAlgoName.trim() || !selectedAlgorithm) return;
    setIsAddAlgoDialogOpen(false);
    setNewAlgoName('');
  };

  // Handle delete algorithm
  const handleDeleteAlgorithm = () => {
    if (!selectedAlgorithm) return;
    setIsDeleteConfirmOpen(false);
    setSelectedAlgorithm(null);
    setAlgorithmParams([]);
  };

  // Handle frequency change
  const handleFrequencyChange = (index: number, frequency: ParameterFrequency['frequency']) => {
    setFrequencies(prev => {
      const next = [...prev];
      next[index] = { ...next[index], frequency };
      return next;
    });
    setHasFrequencyChanges(true);
  };

  // Handle custom frequency change
  const handleCustomFrequencyChange = (index: number, seconds: number) => {
    setFrequencies(prev => {
      const next = [...prev];
      next[index] = { ...next[index], customSeconds: seconds };
      return next;
    });
    setHasFrequencyChanges(true);
  };

  // Save frequency changes
  const handleSaveFrequencies = () => {
    localStorage.setItem('emsx_parameter_frequencies', JSON.stringify(frequencies));
    setHasFrequencyChanges(false);
    setFrequencies(prev => prev.map(f => ({ ...f, lastUpdated: new Date() })));
  };

  // Strategy Data Manager handlers
  const handleClearCache = () => {
    clearFileCache();
    setStrategyMessage({ type: 'success', text: 'All caches cleared' });
    loadStrategyStatus();
  };

  const handleReloadFiles = async () => {
    setIsStrategyLoading(true);
    clearFileCache();
    await loadStrategyStatus();
    setIsStrategyLoading(false);
    setStrategyMessage({ type: 'success', text: 'File cache reloaded' });
  };

  const handleExport = () => {
    exportConfiguration();
    setStrategyMessage({ type: 'success', text: 'Configuration exported. Copy the content to the JSON files.' });
  };

  const handleImport = async () => {
    if (!importFile) {
      setStrategyMessage({ type: 'error', text: 'Please select a file' });
      return;
    }
    setIsStrategyLoading(true);
    const result = await importConfiguration(importFile);
    setIsStrategyLoading(false);
    if (result.success) {
      setStrategyMessage({ type: 'success', text: 'Configuration imported successfully' });
      setImportFile(null);
    } else {
      setStrategyMessage({ type: 'error', text: result.error || 'Import failed' });
    }
  };

  // Render tree node recursively
  const renderTreeNode = (node: TreeNode, level: number = 0) => {
    const isExpanded = expandedNodes.has(node.id);
    const paddingLeft = level * 16 + 12;

    const algoMatch = node.id.startsWith('algo::') ? node.id.split('::') : null;
    // algoMatch: ['algo', exchange, broker, strategy]

    return (
      <div key={node.id}>
        <div
          className={`flex items-center gap-1 py-1.5 px-2 hover:bg-muted/50 cursor-pointer rounded-sm ${
            node.type === 'algorithm' && selectedAlgorithm?.strategy === node.name &&
            algoMatch && selectedAlgorithm?.broker === algoMatch[2]
              ? 'bg-primary/10'
              : ''
          }`}
          style={{ paddingLeft: `${paddingLeft}px` }}
          onClick={() => {
            if (node.children) {
              toggleNode(node.id);
            }
            if (node.type === 'algorithm' && algoMatch) {
              handleSelectAlgorithm(algoMatch[2], algoMatch[3]);
            }
          }}
        >
          {node.children ? (
            isExpanded ? (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronRight className="h-4 w-4 text-muted-foreground" />
            )
          ) : (
            <span className="w-4" />
          )}
          <span className="text-sm">
            {node.type === 'exchange' && '🏢 '}
            {node.type === 'broker' && '🏦 '}
            {node.type === 'algorithm' && '⚙️ '}
            {node.name}
          </span>
        </div>
        {isExpanded && node.children && (
          <div>{node.children.map(child => renderTreeNode(child, level + 1))}</div>
        )}
      </div>
    );
  };

  // Format last updated time
  const formatLastUpdated = (date: Date | null): string => {
    if (!date) return 'Never';
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="flex gap-4 min-h-[600px]">
      {/* ── Left Nav ────────────────────────────────────────────────────── */}
      <nav className="w-56 shrink-0 space-y-0.5 border-r border-border pr-2">
        <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
          Settings
        </div>
        {([
          { id: 'global',              label: 'Global',              icon: Settings },
          { id: 'monitor-conditions',  label: 'Monitor Conditions',  icon: SlidersHorizontal },
          { id: 'broker-algo',         label: 'Broker & Algorithm',  icon: Database },
          { id: 'market-broker-mapping', label: 'Market Broker Mapping', icon: Building2 },
          { id: 'parameter-frequency', label: 'Parameter Frequency', icon: RefreshCw },
          { id: 'data-manager',        label: 'Strategy Data',       icon: FileJson },
          { id: 'about',               label: 'About',               icon: Info },
        ] as const).map(item => {
          const Icon = item.icon;
          const isActive = activeSection === item.id;
          return (
            <button
              key={item.id}
              onClick={() => setActiveSection(item.id)}
              className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-md text-sm text-left transition-colors ${
                isActive
                  ? 'bg-primary/10 text-primary font-medium'
                  : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground'
              }`}
            >
              <Icon className="h-4 w-4" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* ── Right Detail Pane ──────────────────────────────────────────── */}
      <div className="flex-1 space-y-4 min-w-0">
      {/* Global Settings */}
      {activeSection === 'global' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Global Settings</CardTitle>
          </div>
          <CardDescription>Configure application-wide preferences</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Monitor className="h-4 w-4 text-muted-foreground" />
              <div>
                <Label htmlFor="monitor-alerts" className="font-medium">Enable Monitor Alerts</Label>
                <p className="text-xs text-muted-foreground">Activate/deactivate all alert conditions globally</p>
              </div>
            </div>
            <Switch
              id="monitor-alerts"
              checked={monitorAlertsEnabled}
              onCheckedChange={setMonitorAlertsEnabled}
            />
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Bell className="h-4 w-4 text-muted-foreground" />
              <div>
                <Label htmlFor="desktop-notifications" className="font-medium">Enable Desktop Notifications</Label>
                <p className="text-xs text-muted-foreground">Show real-time desktop alert notifications</p>
              </div>
            </div>
            <Switch
              id="desktop-notifications"
              checked={desktopNotificationsEnabled}
              onCheckedChange={setDesktopNotificationsEnabled}
            />
          </div>
        </CardContent>
      </Card>
      )}

      {/* Monitor Conditions */}
      {activeSection === 'monitor-conditions' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Monitor Conditions</CardTitle>
          </div>
          <CardDescription>
            Configure threshold triggers that flag orders on the Monitor Board. Changes apply immediately.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!monitorConditions || !onMonitorConditionsChange ? (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>
                Monitor conditions wiring unavailable. (Host not passing conditions prop.)
              </AlertDescription>
            </Alert>
          ) : (
            <>
              <div className="grid grid-cols-1 gap-2">
                {CONDITION_DEFS.map((def) => {
                  const cfg = monitorConditions[def.id];
                  const isDollar = def.id === 'dollarValueLow' || def.id === 'dollarValueHigh';
                  const isBool = def.isBool;
                  const setField = (patch: Partial<ConditionConfig & BoolConditionConfig>) => {
                    onMonitorConditionsChange({
                      ...monitorConditions,
                      [def.id]: { ...cfg, ...patch },
                    } as MonitorConditions);
                  };
                  return (
                    <div
                      key={def.id}
                      className={`flex items-center gap-3 px-3 py-2 rounded-md border border-border ${
                        cfg.enabled ? '' : 'opacity-60'
                      }`}
                    >
                      <Checkbox
                        checked={cfg.enabled}
                        onCheckedChange={(v) => setField({ enabled: Boolean(v) })}
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium">{def.label} {def.unit}</div>
                        <div className="text-[11px] text-muted-foreground">
                          Preview: {
                            // Approximate match-count; runtime uses full routing context
                            'runtime-evaluated on Monitor Board'
                          }
                        </div>
                      </div>
                      {isBool ? (
                        <Select
                          value={String((cfg as BoolConditionConfig).value)}
                          onValueChange={(v) => setField({ value: v === 'true' })}
                          disabled={!cfg.enabled}
                        >
                          <SelectTrigger className="h-8 w-24 text-xs"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            <SelectItem value="true">Yes</SelectItem>
                            <SelectItem value="false">No</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : (
                        <Input
                          type="number"
                          value={(cfg as ConditionConfig).threshold}
                          onChange={(e) => setField({ threshold: parseFloat(e.target.value) || 0 })}
                          step={isDollar ? 1000 : 0.5}
                          className="h-8 w-32 text-right font-mono"
                          disabled={!cfg.enabled}
                        />
                      )}
                    </div>
                  );
                })}

                {/* Lazy Order — runtime-evaluated condition (needs LazyContext), so rendered inline */}
                {(() => {
                  const lazyCfg = monitorConditions.lazy;
                  return (
                    <div
                      key="lazy"
                      className={`flex items-center gap-3 px-3 py-2 rounded-md border border-border ${
                        lazyCfg.enabled ? '' : 'opacity-60'
                      }`}
                    >
                      <Checkbox
                        checked={lazyCfg.enabled}
                        onCheckedChange={(v) =>
                          onMonitorConditionsChange({
                            ...monitorConditions,
                            lazy: { ...lazyCfg, enabled: Boolean(v) },
                          })
                        }
                      />
                      <div className="flex-1">
                        <div className="text-sm font-medium">Lazy Order</div>
                        <div className="text-[11px] text-muted-foreground">
                          Status \u2209 {'{'}WORKING, QUEUED, COMPLETED, FILLED, SUSPENDED{'}'} or idle share &gt; 0
                        </div>
                      </div>
                      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-sky-100 text-sky-700">
                        Lazy
                      </span>
                    </div>
                  );
                })()}
              </div>

              <div className="border-t border-border pt-3 flex items-center justify-between">
                <div className="text-xs text-muted-foreground">
                  System rules (always on):
                  <span className="ml-2 inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700 mr-1">
                    Critical
                  </span>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => onMonitorConditionsChange(structuredClone(DEFAULT_CONDITIONS))}
                >
                  <RefreshCw className="h-3 w-3 mr-1" />Reset to defaults
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>
      )}

      {/* Broker Algorithm Configuration */}
      {activeSection === 'broker-algo' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Database className="h-5 w-5 text-primary" />
              <CardTitle className="text-base">Broker Algorithm Configuration</CardTitle>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="outline" size="sm" onClick={() => setIsStrategyManagerOpen(true)}>
                <FileJson className="h-4 w-4 mr-2" />
                Strategy Data Manager
              </Button>
            </div>
          </div>
          <CardDescription>
            Configure algorithm parameters by exchange, broker, and strategy
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Status Bar */}
          <div className="flex items-center justify-between mb-4 px-3 py-2 bg-muted/30 rounded-md">
            <div className="flex items-center gap-4 text-sm">
              <div className="flex items-center gap-2">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">Last updated:</span>
                <span className="font-medium">{formatLastUpdated(lastUpdated)}</span>
              </div>
              {isRefreshing && (
                <div className="flex items-center gap-2 text-blue-500">
                  <RefreshCw className="h-4 w-4 animate-spin" />
                  <span>Refreshing...</span>
                </div>
              )}
              {!isRefreshing && lastUpdated && (
                <div className="flex items-center gap-2 text-green-500">
                  <CheckCircle2 className="h-4 w-4" />
                  <span>Up to date</span>
                </div>
              )}
            </div>
            <Button
              variant="outline"
              size="sm"
              onClick={refreshData}
              disabled={isRefreshing}
            >
              <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
              Refresh Now
            </Button>
          </div>

          {error && (
            <Alert variant="destructive" className="mb-4">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          <div className="grid grid-cols-2 gap-4">
            {/* Tree View */}
            <div className="border rounded-md">
              <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Exchange / Broker / Algorithm
                </span>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 text-xs"
                  onClick={() => setIsAddAlgoDialogOpen(true)}
                  disabled={!selectedAlgorithm}
                >
                  <Plus className="h-3 w-3 mr-1" />
                  Add
                </Button>
              </div>
              <ScrollArea className="h-[300px]">
                {isLoading ? (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground">
                    <div className="flex flex-col items-center gap-2">
                      <RefreshCw className="h-6 w-6 animate-spin" />
                      <span className="text-xs">Loading broker algorithms...</span>
                    </div>
                  </div>
                ) : treeData.length === 0 ? (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm px-4 text-center">
                    <div>
                      <p>No broker algorithms available</p>
                      <p className="text-xs mt-1">Click "Refresh Now" to load from Bloomberg API</p>
                    </div>
                  </div>
                ) : (
                  <div className="py-2">{treeData.map(node => renderTreeNode(node))}</div>
                )}
              </ScrollArea>
            </div>

            {/* Parameter Table */}
            <div className="border rounded-md">
              <div className="px-3 py-2 border-b bg-muted/30 flex items-center justify-between">
                <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Algorithm Parameters
                </span>
                {selectedAlgorithm && (
                  <div className="flex items-center gap-1">
                    {hasParamChanges && (
                      <Button variant="default" size="sm" className="h-6 text-xs" onClick={handleSaveParamChanges}>
                        <Save className="h-3 w-3 mr-1" />
                        Save
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 text-xs text-destructive hover:text-destructive"
                      onClick={() => setIsDeleteConfirmOpen(true)}
                    >
                      <Trash2 className="h-3 w-3 mr-1" />
                      Delete
                    </Button>
                  </div>
                )}
              </div>
              <ScrollArea className="h-[300px]">
                {selectedAlgorithm ? (
                  <div className="p-3">
                    <div className="mb-3">
                      <Badge variant="outline" className="text-xs">
                        {selectedAlgorithm.broker} / {selectedAlgorithm.strategy}
                      </Badge>
                    </div>
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
                              <td className="py-2 text-xs">
                                <Badge variant="outline" className="text-[10px]">{param.dataType}</Badge>
                              </td>
                              <td className="py-2">
                                <Input
                                  value={param.stringValue}
                                  onChange={(e) => handleParamChange(idx, e.target.value)}
                                  disabled={param.disable === 'Y'}
                                  className="h-7 text-xs"
                                  placeholder={param.disable === 'Y' ? 'Disabled' : 'Enter value'}
                                />
                              </td>
                              <td className="py-2 text-xs text-muted-foreground max-w-[150px] truncate" title={param.description}>
                                {param.description}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : (
                      <div className="text-center text-muted-foreground py-8">
                        No parameters available for this strategy
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-[200px] text-muted-foreground text-sm">
                    Select an algorithm to view parameters
                  </div>
                )}
              </ScrollArea>
            </div>
          </div>
        </CardContent>
      </Card>
      )}

      {/* Market Broker Mapping */}
      {activeSection === 'market-broker-mapping' && (
        <MarketBrokerMappingSection />
      )}

      {/* Parameter Update Frequency */}
      {activeSection === 'parameter-frequency' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <RefreshCw className="h-5 w-5 text-primary" />
              <CardTitle className="text-base">Parameter Update Frequency</CardTitle>
            </div>
            {hasFrequencyChanges && (
              <Button size="sm" onClick={handleSaveFrequencies}>
                <Save className="h-4 w-4 mr-2" />
                Save Changes
              </Button>
            )}
          </div>
          <CardDescription>Configure refresh intervals for system parameters</CardDescription>
        </CardHeader>
        <CardContent>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b">
                <th className="text-left py-2 font-semibold">Parameter Name</th>
                <th className="text-left py-2 font-semibold">Current Frequency</th>
                <th className="text-left py-2 font-semibold">Last Updated</th>
              </tr>
            </thead>
            <tbody>
              {frequencies.map((freq, idx) => (
                <tr key={freq.parameterName} className="border-b border-border/50">
                  <td className="py-2">{freq.parameterName}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <Select
                        value={freq.frequency}
                        onValueChange={(v) => handleFrequencyChange(idx, v as ParameterFrequency['frequency'])}
                      >
                        <SelectTrigger className="h-7 w-36 text-xs">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {FREQUENCY_OPTIONS.map(opt => (
                            <SelectItem key={opt.value} value={opt.value} className="text-xs">
                              {opt.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {freq.frequency === 'custom' && (
                        <Input
                          type="number"
                          value={freq.customSeconds || ''}
                          onChange={(e) => handleCustomFrequencyChange(idx, parseInt(e.target.value) || 0)}
                          className="h-7 w-20 text-xs"
                          placeholder="secs"
                          min={1}
                        />
                      )}
                    </div>
                  </td>
                  <td className="py-2 text-muted-foreground text-xs">
                    {freq.lastUpdated.toLocaleTimeString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      )}

      {/* Data Manager (Strategy Files) */}
      {activeSection === 'data-manager' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <FileJson className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Strategy Data Files</CardTitle>
          </div>
          <CardDescription>
            Inspect cached strategy parameter files and import/export configurations.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setIsStrategyManagerOpen(true)}>
              <FileJson className="h-4 w-4 mr-2" />Open Strategy Data Manager
            </Button>
            <Button variant="outline" size="sm" onClick={handleExport}>
              <Download className="h-4 w-4 mr-2" />Export
            </Button>
            <label className="inline-flex">
              <Button variant="outline" size="sm" asChild>
                <span>
                  <Upload className="h-4 w-4 mr-2" />Import
                  <input
                    type="file"
                    accept="application/json"
                    className="hidden"
                    onChange={(e) => setImportFile(e.target.files?.[0] ?? null)}
                  />
                </span>
              </Button>
            </label>
            {importFile && (
              <Button size="sm" onClick={handleImport} disabled={isStrategyLoading}>
                Apply {importFile.name}
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
      )}

      {/* About */}
      {activeSection === 'about' && (
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <Info className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">About</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <div className="flex justify-between"><span className="text-muted-foreground">Version</span><span className="font-mono">EMSX Trading Tool v1.0.0</span></div>
          <div className="flex justify-between"><span className="text-muted-foreground">API Endpoint</span><span className="font-mono">{import.meta.env.VITE_API_URL || window.location.origin}</span></div>
          <div className="flex justify-between"><span className="text-muted-foreground">Build Mode</span><span className="font-mono">{import.meta.env.MODE}</span></div>
        </CardContent>
      </Card>
      )}

      </div>{/* end right-pane */}

      {/* Add Algorithm Dialog */}
      <Dialog open={isAddAlgoDialogOpen} onOpenChange={setIsAddAlgoDialogOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Plus className="h-5 w-5" />
              Add New Algorithm
            </DialogTitle>
            <DialogDescription>
              Create a new algorithm for {selectedAlgorithm?.broker}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label>Algorithm Name</Label>
              <Input
                value={newAlgoName}
                onChange={(e) => setNewAlgoName(e.target.value)}
                placeholder="e.g., VWAP, TWAP, Arrival Price"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAddAlgoDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleAddAlgorithm} disabled={!newAlgoName.trim()}>
              Create Algorithm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Algorithm Confirmation */}
      <Dialog open={isDeleteConfirmOpen} onOpenChange={setIsDeleteConfirmOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-5 w-5" />
              Delete Algorithm
            </DialogTitle>
            <DialogDescription>
              Are you sure you want to delete <strong>{selectedAlgorithm?.strategy}</strong> for {selectedAlgorithm?.broker}?
              This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDeleteConfirmOpen(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleDeleteAlgorithm}>
              <Trash2 className="h-4 w-4 mr-2" />
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Strategy Data Manager Dialog */}
      <Dialog open={isStrategyManagerOpen} onOpenChange={setIsStrategyManagerOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileJson className="h-5 w-5" />
              Strategy Data Manager
            </DialogTitle>
            <DialogDescription>
              Import/export strategy parameter configurations
            </DialogDescription>
          </DialogHeader>

          {strategyMessage && (
            <Alert variant={strategyMessage.type === 'error' ? 'destructive' : 'default'} className="mb-4">
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{strategyMessage.text}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-4 py-4">
            {/* Cache Status */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase">Cache Status</Label>
              <div className="grid grid-cols-2 gap-2 text-sm">
                <div className="bg-muted p-2 rounded">
                  <div className="text-xs text-muted-foreground">File Cache</div>
                  <div className="font-medium">{fileStatus?.initialized ? 'Ready' : 'Not Loaded'}</div>
                  <div className="text-xs text-muted-foreground">
                    {fileStatus?.strategiesCount || 0} brokers, {fileStatus?.paramsCount || 0} strategies
                  </div>
                </div>
                <div className="bg-muted p-2 rounded">
                  <div className="text-xs text-muted-foreground">API Data</div>
                  <div className="font-medium">{configs.length} brokers</div>
                  <div className="text-xs text-muted-foreground">
                    {configs.reduce((acc, c) => acc + c.strategies.length, 0)} strategies
                  </div>
                </div>
              </div>
            </div>

            {/* Available Brokers */}
            {brokers.length > 0 && (
              <div className="space-y-2">
                <Label className="text-xs font-semibold uppercase">Available Brokers in Files</Label>
                <div className="flex flex-wrap gap-1">
                  {brokers.map(broker => (
                    <Badge key={broker} variant="secondary" className="text-xs">{broker}</Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Actions */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase">Actions</Label>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={handleClearCache}>
                  <RefreshCw className="h-4 w-4 mr-2" />
                  Clear Cache
                </Button>
                <Button variant="outline" size="sm" onClick={handleReloadFiles} disabled={isStrategyLoading}>
                  {isStrategyLoading ? (
                    <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                  ) : (
                    <Database className="h-4 w-4 mr-2" />
                  )}
                  Reload Files
                </Button>
              </div>
            </div>

            {/* Export */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase">Export Configuration</Label>
              <Button variant="outline" size="sm" onClick={handleExport} className="w-full">
                <Download className="h-4 w-4 mr-2" />
                Export Current Configuration
              </Button>
              <p className="text-xs text-muted-foreground">
                Exports from API cache to JSON format for sharing
              </p>
            </div>

            {/* Import */}
            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase">Import Configuration</Label>
              <div className="flex gap-2">
                <Input
                  type="file"
                  accept=".json"
                  onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                  className="flex-1 text-xs h-9"
                />
                <Button
                  size="sm"
                  onClick={handleImport}
                  disabled={!importFile || isStrategyLoading}
                >
                  <Upload className="h-4 w-4 mr-2" />
                  Import
                </Button>
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsStrategyManagerOpen(false)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
