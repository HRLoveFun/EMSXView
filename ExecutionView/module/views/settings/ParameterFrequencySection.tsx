import { useState } from 'react';
import { RefreshCw, Save } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

interface ParameterFrequency {
  parameterName: string;
  frequency: 'realtime' | '5s' | '30s' | '1m' | 'custom';
  customSeconds?: number;
  lastUpdated: Date;
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

export function ParameterFrequencySection() {
  const [frequencies, setFrequencies] = useState<ParameterFrequency[]>(DEFAULT_FREQUENCIES);
  const [hasFrequencyChanges, setHasFrequencyChanges] = useState(false);

  const handleFrequencyChange = (index: number, frequency: ParameterFrequency['frequency']) => {
    setFrequencies(prev => {
      const next = [...prev];
      next[index] = { ...next[index], frequency };
      return next;
    });
    setHasFrequencyChanges(true);
  };

  const handleCustomFrequencyChange = (index: number, seconds: number) => {
    setFrequencies(prev => {
      const next = [...prev];
      next[index] = { ...next[index], customSeconds: seconds };
      return next;
    });
    setHasFrequencyChanges(true);
  };

  const handleSaveFrequencies = () => {
    localStorage.setItem('emsx_parameter_frequencies', JSON.stringify(frequencies));
    setHasFrequencyChanges(false);
    setFrequencies(prev => prev.map(f => ({ ...f, lastUpdated: new Date() })));
  };

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <RefreshCw className="h-5 w-5 text-primary" />
            <CardTitle className="text-base">Parameter Update Frequency</CardTitle>
          </div>
          {hasFrequencyChanges && (
            <Button size="sm" onClick={handleSaveFrequencies}>
              <Save className="h-4 w-4 mr-2" />Save Changes
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
                    <Select value={freq.frequency} onValueChange={(v) => handleFrequencyChange(idx, v as ParameterFrequency['frequency'])}>
                      <SelectTrigger className="h-7 w-36 text-xs">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {FREQUENCY_OPTIONS.map(opt => (
                          <SelectItem key={opt.value} value={opt.value} className="text-xs">{opt.label}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {freq.frequency === 'custom' && (
                      <Input type="number" value={freq.customSeconds || ''} onChange={(e) => handleCustomFrequencyChange(idx, parseInt(e.target.value) || 0)} className="h-7 w-20 text-xs" placeholder="secs" min={1} />
                    )}
                  </div>
                </td>
                <td className="py-2 text-muted-foreground text-xs">{freq.lastUpdated.toLocaleTimeString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
