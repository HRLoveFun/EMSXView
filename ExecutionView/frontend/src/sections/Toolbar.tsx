import { RefreshCw, Wifi, WifiOff, Activity, Database, LogOut, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import type { ConnectionStatus, StartupStatusSnapshot } from '@/types';

interface ToolbarProps {
  onRefresh: () => void;
  onClearCache?: () => void;
  isLoading: boolean;
  orderCount: number;
  onLogout: () => void;
  startupStatus: StartupStatusSnapshot | null;
  connectionStatus: ConnectionStatus;
  checkingStartup: boolean;
}

export function Toolbar({
  onRefresh,
  onClearCache,
  isLoading,
  orderCount,
  onLogout,
  startupStatus,
  connectionStatus,
  checkingStartup,
}: ToolbarProps) {
  const lastUpdated = new Date();

  const handleRefresh = async () => {
    await onRefresh();
  };

  const getConnectionIcon = () => {
    if (checkingStartup) {
      return <Spinner className="h-4 w-4" />;
    }
    switch (connectionStatus) {
      case 'connected':
        return <Wifi className="h-4 w-4" />;
      case 'disconnected':
        return <WifiOff className="h-4 w-4" />;
      default:
        return <Activity className="h-4 w-4 animate-pulse" />;
    }
  };

  const getConnectionClass = () => {
    switch (connectionStatus) {
      case 'connected':
        return 'connection-connected';
      case 'disconnected':
        return 'connection-disconnected';
      default:
        return 'connection-pending';
    }
  };

  const getConnectionText = () => {
    if (!startupStatus) {
      return 'Checking startup...';
    }
    switch (startupStatus.phase) {
      case 'ready':
        return 'Ready';
      case 'backend_starting':
        return 'Backend starting';
      case 'bloomberg_connecting':
        return 'Connecting Bloomberg';
      case 'subscriptions_warming':
        return 'Warming subscriptions';
      case 'error':
        return 'Attention needed';
      default:
        return 'Starting...';
    }
  };

  return (
    <div className="toolbar">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-semibold">EMSX Trading Tool</h1>
        </div>
        
        <div className="h-6 w-px bg-border mx-2" />
        
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>Orders:</span>
          <Badge variant="secondary" className="font-mono-numbers">
            {orderCount.toLocaleString()}
          </Badge>
        </div>
        
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>Last Updated:</span>
          <span className="font-mono-numbers">
            {lastUpdated.toLocaleTimeString()}
          </span>
        </div>
      </div>
      
      <div className="flex items-center gap-3">
        <div className={`flex items-center gap-2 text-sm ${getConnectionClass()}`} title={startupStatus?.message ?? getConnectionText()}>
          {getConnectionIcon()}
          <span className="font-medium">{getConnectionText()}</span>
        </div>
        
        <div className="h-6 w-px bg-border mx-1" />
        
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="outline"
              size="sm"
              disabled={isLoading}
              className="gap-2"
            >
              {isLoading ? <Spinner className="h-4 w-4" /> : <RefreshCw className="h-4 w-4" />}
              Refresh
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={handleRefresh}>
              <RefreshCw className="h-4 w-4 mr-2" />
              Refresh Data
            </DropdownMenuItem>
            {onClearCache && (
              <DropdownMenuItem onClick={onClearCache}>
                <Trash2 className="h-4 w-4 mr-2" />
                Clear Cache
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <Button
          variant="ghost"
          size="sm"
          onClick={onLogout}
          className="gap-2 text-muted-foreground hover:text-destructive"
          title="退出登录"
        >
          <LogOut className="h-4 w-4" />
          退出
        </Button>
      </div>
    </div>
  );
}
