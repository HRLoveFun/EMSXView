import { useState, useEffect } from 'react';
import { Building2, GitBranch, Info } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { GlobalSection } from './GlobalSection';
import { MonitorConditionsSection } from './MonitorConditionsSection';
import { BrokerAlgoSection } from './BrokerAlgoSection';
import { ParameterFrequencySection } from './ParameterFrequencySection';
import { StrategyDataSection } from './StrategyDataSection';
import { SettingsNav, type SettingsSectionId } from './SettingsNav';
import { MarketBrokerMappingSection as MarketBrokerMappingComponent } from '@execution/components/market-broker-mapping-section';
import { RoutePlanManager } from '@execution/components/route-plan-manager';
import type { MonitorConditions } from '@execution/lib/monitor-conditions';

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

  const renderSection = () => {
    switch (activeSection) {
      case 'global':              return <GlobalSection />;
      case 'monitor-conditions':  return <MonitorConditionsSection monitorConditions={monitorConditions} onMonitorConditionsChange={onMonitorConditionsChange} />;
      case 'broker-algo':         return <BrokerAlgoSection />;
      case 'market-broker-mapping':
        return (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <Building2 className="h-5 w-5 text-primary" />
                <CardTitle className="text-base">Market Broker Mapping</CardTitle>
              </div>
              <CardDescription>Configure broker availability per exchange market</CardDescription>
            </CardHeader>
            <CardContent>
              <MarketBrokerMappingComponent />
            </CardContent>
          </Card>
        );
      case 'parameter-frequency': return <ParameterFrequencySection />;
      case 'route-plans':
        return (
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center gap-2">
                <GitBranch className="h-5 w-5 text-primary" />
                <CardTitle className="text-base">Route Plan Management</CardTitle>
              </div>
              <CardDescription>
                Predefined route plan templates: match conditions + Broker allocation / time-split strategies. New orders can be auto/manually matched to generate pending sub-order proposals.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <RoutePlanManager />
            </CardContent>
          </Card>
        );
      case 'data-manager':        return <StrategyDataSection />;
      case 'about':
        return (
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
        );
    }
  };

  return (
    <div className="flex gap-4 min-h-[600px]">
      <SettingsNav activeSection={activeSection} onNavigate={setActiveSection} />
      <div className="flex-1 min-w-0">
        {renderSection()}
      </div>
    </div>
  );
}
