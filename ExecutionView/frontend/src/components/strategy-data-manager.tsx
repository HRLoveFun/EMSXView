/**
 * Strategy Data Manager - Developer tool for managing strategy configuration files
 * 
 * Features:
 * - View current file cache status
 * - Export current configuration
 * - Import configuration from file
 * - Clear and reload file cache
 * - Edit default parameter values
 */

import { useState, useEffect, useCallback } from 'react';
import { FileJson, Download, Upload, RefreshCw, Database, AlertCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  getFileCacheStatus,
  clearFileCache,
  exportConfiguration,
  importConfiguration,
  getAvailableBrokersFromFile,
} from '@/services/strategy-data-service';
import { cachedApiService } from '@/services/api';

interface CacheStatus {
  initialized: boolean;
  strategiesCount: number;
  paramsCount: number;
  lastLoaded: string | null;
}

interface ApiCacheStatus {
  brokerStrategiesCached: number;
  strategyInfoCached: number;
}

export function StrategyDataManager() {
  const [isOpen, setIsOpen] = useState(false);
  const [fileStatus, setFileStatus] = useState<CacheStatus | null>(null);
  const [apiStatus, setApiStatus] = useState<ApiCacheStatus | null>(null);
  const [brokers, setBrokers] = useState<string[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const loadStatus = useCallback(async () => {
    setFileStatus(getFileCacheStatus());
    setApiStatus(cachedApiService.getCacheStatus());
    const brokerList = await getAvailableBrokersFromFile();
    setBrokers(brokerList);
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadStatus();
    }
  }, [isOpen, loadStatus]);

  const handleClearCache = () => {
    clearFileCache();
    cachedApiService.clearBrokerStrategyCaches();
    setMessage({ type: 'success', text: 'All caches cleared' });
    loadStatus();
  };

  const handleReloadFiles = async () => {
    setIsLoading(true);
    clearFileCache();
    await loadStatus();
    setIsLoading(false);
    setMessage({ type: 'success', text: 'File cache reloaded' });
  };

  const handleExport = () => {
    // Export current cache from LocalStorage (contains real API data)
    exportConfiguration();
    setMessage({ type: 'success', text: 'Configuration exported from cache. Copy the content to the JSON files.' });
  };

  const handleImport = async () => {
    if (!importFile) {
      setMessage({ type: 'error', text: 'Please select a file' });
      return;
    }

    const result = await importConfiguration(importFile);
    if (result.success) {
      setMessage({ type: 'success', text: 'Configuration imported successfully' });
      setImportFile(null);
    } else {
      setMessage({ type: 'error', text: result.error || 'Import failed' });
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Database className="h-4 w-4" />
          Strategy Data
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-lg max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileJson className="h-5 w-5" />
            Strategy Data Manager
          </DialogTitle>
          <DialogDescription>
            Manage broker strategy configuration files and caching
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Status Overview */}
          <Accordion type="single" collapsible defaultValue="status">
            <AccordionItem value="status">
              <AccordionTrigger>Cache Status</AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 text-sm">
                  <div className="bg-secondary/50 p-3 rounded space-y-2">
                    <div className="font-medium">File Cache</div>
                    <div className="grid grid-cols-2 gap-2 text-muted-foreground">
                      <div>Initialized:</div>
                      <div>
                        {fileStatus?.initialized ? (
                          <Badge variant="default" className="text-xs">Yes</Badge>
                        ) : (
                          <Badge variant="secondary" className="text-xs">No</Badge>
                        )}
                      </div>
                      <div>Strategies:</div>
                      <div>{fileStatus?.strategiesCount || 0} brokers</div>
                      <div>Parameters:</div>
                      <div>{fileStatus?.paramsCount || 0} strategies</div>
                      <div>Last Loaded:</div>
                      <div>{fileStatus?.lastLoaded ? new Date(fileStatus.lastLoaded).toLocaleString() : 'Never'}</div>
                    </div>
                  </div>

                  <div className="bg-secondary/50 p-3 rounded space-y-2">
                    <div className="font-medium">API Cache (Memory)</div>
                    <div className="grid grid-cols-2 gap-2 text-muted-foreground">
                      <div>Broker Strategies:</div>
                      <div>{apiStatus?.brokerStrategiesCached || 0} cached</div>
                      <div>Strategy Info:</div>
                      <div>{apiStatus?.strategyInfoCached || 0} cached</div>
                    </div>
                  </div>

                  <div className="bg-secondary/50 p-3 rounded space-y-2">
                    <div className="font-medium">Available Brokers</div>
                    <div className="flex flex-wrap gap-1">
                      {brokers.length > 0 ? (
                        brokers.map(broker => (
                          <Badge key={broker} variant="outline" className="text-xs">
                            {broker}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-muted-foreground">No brokers loaded</span>
                      )}
                    </div>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="actions">
              <AccordionTrigger>Actions</AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3">
                  <div className="flex gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleReloadFiles}
                      disabled={isLoading}
                      className="flex-1 gap-2"
                    >
                      <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
                      Reload Files
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleClearCache}
                      className="flex-1 gap-2"
                    >
                      Clear All Caches
                    </Button>
                  </div>

                  <div className="border-t pt-3">
                    <div className="font-medium text-sm mb-2">Export / Import</div>
                    <div className="flex gap-2">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleExport}
                        className="flex-1 gap-2"
                      >
                        <Download className="h-4 w-4" />
                        Export Config
                      </Button>
                    </div>
                    <div className="mt-2 flex gap-2 items-end">
                      <div className="flex-1 space-y-1">
                        <Label className="text-xs">Import Configuration</Label>
                        <Input
                          type="file"
                          accept=".json"
                          onChange={(e) => setImportFile(e.target.files?.[0] || null)}
                          className="h-8 text-xs"
                        />
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={handleImport}
                        disabled={!importFile}
                        className="gap-2"
                      >
                        <Upload className="h-4 w-4" />
                        Import
                      </Button>
                    </div>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>

            <AccordionItem value="files">
              <AccordionTrigger>Configuration Files</AccordionTrigger>
              <AccordionContent>
                <div className="space-y-3 text-sm">
                  <div className="bg-secondary/50 p-3 rounded">
                    <div className="font-medium">File Locations</div>
                    <div className="mt-2 space-y-1 text-muted-foreground text-xs">
                      <div><code>public/strategy-data/default-strategies.json</code></div>
                      <div><code>public/strategy-data/default-strategy-params.json</code></div>
                    </div>
                  </div>

                  <div className="bg-amber-50 border border-amber-200 p-3 rounded flex gap-2">
                    <AlertCircle className="h-4 w-4 text-amber-600 shrink-0 mt-0.5" />
                    <div className="text-xs text-amber-800">
                      <strong>Important:</strong> Data must come from Bloomberg API. 
                      1) Connect to Bloomberg, 2) Use strategies to populate cache, 
                      3) Click "Export Config" to get real data, 4) Copy to these files.
                    </div>
                  </div>
                </div>
              </AccordionContent>
            </AccordionItem>
          </Accordion>

          {/* Message */}
          {message && (
            <div className={`p-3 rounded text-sm ${
              message.type === 'success' ? 'bg-green-50 text-green-800 border border-green-200' : 'bg-red-50 text-red-800 border border-red-200'
            }`}>
              {message.text}
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
