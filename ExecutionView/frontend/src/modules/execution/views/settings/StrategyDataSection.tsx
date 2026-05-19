import { useState } from 'react';
import { FileJson, Download, Upload, AlertCircle } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription } from '@/components/ui/alert';
import {
  exportConfiguration,
  importConfiguration,
} from '@execution/services/strategy-data-service';
import { useBrokerAlgorithms } from '@execution/hooks/use-broker-algorithms';
import { StrategyDataManagerDialog } from '@execution/components/strategy-data-manager-dialog';

export function StrategyDataSection() {
  const { configs } = useBrokerAlgorithms();
  const [isStrategyManagerOpen, setIsStrategyManagerOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [strategyMessage, setStrategyMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);
  const [isStrategyLoading, setIsStrategyLoading] = useState(false);

  const handleImport = async () => {
    if (!importFile) { setStrategyMessage({ type: 'error', text: 'Please select a file' }); return; }
    setIsStrategyLoading(true);
    const result = await importConfiguration(importFile);
    setIsStrategyLoading(false);
    setStrategyMessage(result.success ? { type: 'success', text: 'Configuration imported successfully' } : { type: 'error', text: result.error || 'Import failed' });
    if (result.success) setImportFile(null);
  };

  return (
    <>
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <FileJson className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Strategy Data Files</CardTitle>
          </div>
          <CardDescription>Inspect cached strategy parameter files and import/export configurations.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {strategyMessage && (
            <Alert variant={strategyMessage.type === 'error' ? 'destructive' : 'default'}>
              <AlertCircle className="h-4 w-4" /><AlertDescription>{strategyMessage.text}</AlertDescription>
            </Alert>
          )}
          <div className="flex items-center gap-2">
            <Button variant="outline" size="sm" onClick={() => setIsStrategyManagerOpen(true)}>
              <FileJson className="h-4 w-4 mr-2" />Open Strategy Data Manager
            </Button>
            <Button variant="outline" size="sm" onClick={() => { exportConfiguration(); setStrategyMessage({ type: 'success', text: 'Configuration exported' }); }}>
              <Download className="h-4 w-4 mr-2" />Export
            </Button>
            <label className="inline-flex">
              <Button variant="outline" size="sm" asChild>
                <span>
                  <Upload className="h-4 w-4 mr-2" />Import
                  <input type="file" accept="application/json" className="hidden" onChange={(e) => setImportFile(e.target.files?.[0] ?? null)} />
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

      <StrategyDataManagerDialog open={isStrategyManagerOpen} onOpenChange={setIsStrategyManagerOpen} configs={configs} />
    </>
  );
}
