import { useState, useCallback, useEffect } from 'react';
import { FileJson, Download, Upload, Database, RefreshCw, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  Dialog, DialogContent, DialogDescription, DialogFooter,
  DialogHeader, DialogTitle,
} from '@/components/ui/dialog';
import {
  getFileCacheStatus,
  clearFileCache,
  exportConfiguration,
  importConfiguration,
  getAvailableBrokersFromFile,
} from '@execution/services/strategy-data-service';
import type { BrokerAlgorithmConfig } from '@execution/types';

interface StrategyDataManagerDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  configs: BrokerAlgorithmConfig[];
}

export function StrategyDataManagerDialog({ open, onOpenChange, configs }: StrategyDataManagerDialogProps) {
  const [fileStatus, setFileStatus] = useState<{ initialized: boolean; strategiesCount: number; paramsCount: number; lastLoaded: string | null } | null>(null);
  const [brokers, setBrokers] = useState<string[]>([]);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [strategyMessage, setStrategyMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isStrategyLoading, setIsStrategyLoading] = useState(false);

  const loadStrategyStatus = useCallback(async () => {
    // setState 放在 await 之后（异步），避免 effect 内同步 setState
    const brokerList = await getAvailableBrokersFromFile();
    setFileStatus(getFileCacheStatus());
    setBrokers(brokerList);
  }, []);

  useEffect(() => {
    if (open) {
      // 在微任务中触发加载，避免 effect 同步路径调用含 setState 的函数
      queueMicrotask(() => { void loadStrategyStatus(); });
    }
  }, [open, loadStrategyStatus]);

  const handleImport = async () => {
    if (!importFile) { setStrategyMessage({ type: 'error', text: 'Please select a file' }); return; }
    setIsStrategyLoading(true);
    const result = await importConfiguration(importFile);
    setIsStrategyLoading(false);
    setStrategyMessage(result.success ? { type: 'success', text: 'Configuration imported successfully' } : { type: 'error', text: result.error || 'Import failed' });
    if (result.success) setImportFile(null);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><FileJson className="h-5 w-5" />Strategy Data Manager</DialogTitle>
          <DialogDescription>Import/export strategy parameter configurations</DialogDescription>
        </DialogHeader>

        {strategyMessage && (
          <Alert variant={strategyMessage.type === 'error' ? 'destructive' : 'default'} className="mb-4">
            <AlertCircle className="h-4 w-4" /><AlertDescription>{strategyMessage.text}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-4 py-4">
          <div className="space-y-2">
            <Label className="text-xs font-semibold uppercase">Cache Status</Label>
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="bg-muted p-2 rounded">
                <div className="text-xs text-muted-foreground">File Cache</div>
                <div className="font-medium">{fileStatus?.initialized ? 'Ready' : 'Not Loaded'}</div>
                <div className="text-xs text-muted-foreground">{fileStatus?.strategiesCount || 0} brokers, {fileStatus?.paramsCount || 0} strategies</div>
              </div>
              <div className="bg-muted p-2 rounded">
                <div className="text-xs text-muted-foreground">API Data</div>
                <div className="font-medium">{configs.length} brokers</div>
                <div className="text-xs text-muted-foreground">{configs.reduce((acc, c) => acc + c.strategies.length, 0)} strategies</div>
              </div>
            </div>
          </div>

          {brokers.length > 0 && (
            <div className="space-y-2">
              <Label className="text-xs font-semibold uppercase">Available Brokers in Files</Label>
              <div className="flex flex-wrap gap-1">
                {brokers.map(broker => <Badge key={broker} variant="secondary" className="text-xs">{broker}</Badge>)}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <Label className="text-xs font-semibold uppercase">Actions</Label>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => { clearFileCache(); setStrategyMessage({ type: 'success', text: 'All caches cleared' }); loadStrategyStatus(); }}>
                <RefreshCw className="h-4 w-4 mr-2" />Clear Cache
              </Button>
              <Button variant="outline" size="sm" disabled={isStrategyLoading} onClick={async () => { setIsStrategyLoading(true); clearFileCache(); await loadStrategyStatus(); setIsStrategyLoading(false); setStrategyMessage({ type: 'success', text: 'File cache reloaded' }); }}>
                <Database className="h-4 w-4 mr-2" />Reload Files
              </Button>
            </div>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-semibold uppercase">Export Configuration</Label>
            <Button variant="outline" size="sm" onClick={() => { exportConfiguration(); setStrategyMessage({ type: 'success', text: 'Configuration exported' }); }} className="w-full">
              <Download className="h-4 w-4 mr-2" />Export Current Configuration
            </Button>
          </div>

          <div className="space-y-2">
            <Label className="text-xs font-semibold uppercase">Import Configuration</Label>
            <div className="flex gap-2">
              <Input type="file" accept=".json" onChange={(e) => setImportFile(e.target.files?.[0] || null)} className="flex-1 text-xs h-9" />
              <Button size="sm" disabled={!importFile || isStrategyLoading} onClick={handleImport}>
                <Upload className="h-4 w-4 mr-2" />Import
              </Button>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
