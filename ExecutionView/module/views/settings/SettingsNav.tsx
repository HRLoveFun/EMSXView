import { Settings, SlidersHorizontal, Database, Building2, RefreshCw, GitBranch, FileJson, Info } from 'lucide-react';
export type SettingsSectionId =
  | 'global'
  | 'monitor-conditions'
  | 'broker-algo'
  | 'market-broker-mapping'
  | 'parameter-frequency'
  | 'route-plans'
  | 'data-manager'
  | 'about';

const NAV_ITEMS: { id: SettingsSectionId; label: string; icon: React.FC<{ className?: string }> }[] = [
  { id: 'global',              label: 'Global',              icon: Settings },
  { id: 'monitor-conditions',  label: 'Monitor Conditions',  icon: SlidersHorizontal },
  { id: 'broker-algo',         label: 'Broker & Algorithm',  icon: Database },
  { id: 'market-broker-mapping', label: 'Market Broker Mapping', icon: Building2 },
  { id: 'parameter-frequency', label: 'Parameter Frequency', icon: RefreshCw },
  { id: 'route-plans',         label: 'Route Plans',         icon: GitBranch },
  { id: 'data-manager',        label: 'Strategy Data',       icon: FileJson },
  { id: 'about',               label: 'About',               icon: Info },
];

interface SettingsNavProps {
  activeSection: SettingsSectionId;
  onNavigate: (id: SettingsSectionId) => void;
}

export function SettingsNav({ activeSection, onNavigate }: SettingsNavProps) {
  return (
    <nav className="w-56 shrink-0 space-y-0.5 border-r border-border pr-2">
      <div className="px-2 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
        Settings
      </div>
      {NAV_ITEMS.map(item => {
        const Icon = item.icon;
        const isActive = activeSection === item.id;
        return (
          <button
            key={item.id}
            onClick={() => onNavigate(item.id)}
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
  );
}
