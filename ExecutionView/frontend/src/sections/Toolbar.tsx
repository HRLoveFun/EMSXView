import { useEffect, useState } from 'react';
import { RefreshCw, Wifi, WifiOff, Activity, Database, LogOut, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Spinner } from '@/components/ui/spinner';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
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
  /** Real timestamp of the most recent successful data refresh (REST or WS).
   *  Required so the toolbar stops lying about "Last Updated" by re-evaluating
   *  `new Date()` on every render. Pass `null` when no data has arrived yet. */
  lastUpdatedAt: number | null;
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
  lastUpdatedAt,
}: ToolbarProps) {
  // Re-render once a second so the "x seconds ago" relative label stays
  // current. Required because lastUpdatedAt itself only changes on data
  // refresh; without this tick the label would freeze between updates.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setNowTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Two-line label: an absolute clock time (so traders can correlate with
  // Bloomberg) and a relative "ago" so a frozen feed becomes obvious instead
  // of looking fresh forever.
  const lastUpdatedLabel = (() => {
    if (!lastUpdatedAt) return { abs: '—', rel: 'no data yet' };
    const ageMs = Date.now() - lastUpdatedAt;
    const ageSec = Math.max(0, Math.floor(ageMs / 1000));
    const rel =
      ageSec < 5 ? 'just now'
      : ageSec < 60 ? `${ageSec}s ago`
      : ageSec < 3600 ? `${Math.floor(ageSec / 60)}m ago`
      : `${Math.floor(ageSec / 3600)}h ago`;
    return { abs: new Date(lastUpdatedAt).toLocaleTimeString(), rel };
  })();
  const isStale = lastUpdatedAt !== null && (Date.now() - lastUpdatedAt) > 30_000;

  // Logout confirmation gate — prevents an accidental click from wiping the
  // session and silently destroying any in-progress Modify Route / Modify
  // Order edits the user has not yet submitted.
  const [showLogoutConfirm, setShowLogoutConfirm] = useState(false);

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
      return '检查启动状态…';
    }
    switch (startupStatus.phase) {
      case 'ready':
        return '已就绪';
      case 'backend_starting':
        return '后端启动中';
      case 'bloomberg_connecting':
        return '连接 Bloomberg';
      case 'subscriptions_warming':
        return '订阅热身';
      case 'error':
        return '需要人工检查';
      default:
        return '启动中…';
    }
  };

  return (
    <div className="toolbar">
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <Database className="h-5 w-5 text-primary" />
          <h1 className="text-lg font-semibold">EMSX 交易工作台</h1>
        </div>

        <div className="h-6 w-px bg-border mx-2" />

        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <span>订单数：</span>
          <Badge variant="secondary" className="font-mono-numbers">
            {orderCount.toLocaleString()}
          </Badge>
        </div>

        <div
          className={`flex items-center gap-2 text-sm ${isStale ? 'text-amber-600 dark:text-amber-400' : 'text-muted-foreground'}`}
          title={isStale ? '数据已超过 30 秒未刷新，可能已断流' : undefined}
        >
          <span>最近更新：</span>
          <span className="font-mono-numbers">{lastUpdatedLabel.abs}</span>
          <span className="text-xs opacity-80">({lastUpdatedLabel.rel})</span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className={`flex items-center gap-2 text-sm ${getConnectionClass()}`} title={startupStatus?.message ?? getConnectionText()}>
          {getConnectionIcon()}
          <span className="font-medium">{getConnectionText()}</span>
        </div>

        <div className="h-6 w-px bg-border mx-1" />

        {/* Direct Refresh button — single-click action. Clear Cache is a
            secondary destructive action behind a dropdown so it cannot be
            triggered by muscle memory while reaching for refresh. */}
        <Button
          variant="outline"
          size="sm"
          onClick={handleRefresh}
          disabled={isLoading}
          className="gap-2"
          title="重新拉取订单与路由（R）"
        >
          {isLoading ? <Spinner className="h-4 w-4" /> : <RefreshCw className="h-4 w-4" />}
          刷新
        </Button>

        {onClearCache && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                disabled={isLoading}
                className="px-2"
                title="更多操作"
                aria-label="更多操作"
              >
                ⋯
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={onClearCache}>
                <Trash2 className="h-4 w-4 mr-2" />
                清空本地缓存
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowLogoutConfirm(true)}
          className="gap-2 text-muted-foreground hover:text-destructive"
          title="退出登录"
        >
          <LogOut className="h-4 w-4" />
          退出
        </Button>
      </div>

      <AlertDialog open={showLogoutConfirm} onOpenChange={setShowLogoutConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>确认退出登录？</AlertDialogTitle>
            <AlertDialogDescription>
              退出后将关闭与后端的会话。任何未提交的改单 / 路由编辑将会丢失，需要重新登录后再操作。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => { setShowLogoutConfirm(false); onLogout(); }}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              确认退出
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
