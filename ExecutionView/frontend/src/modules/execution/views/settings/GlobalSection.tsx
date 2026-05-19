import { useState, useEffect } from 'react';
import { Settings, Monitor, Bell, RefreshCw } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  RECONCILE_INTERVAL_OPTIONS,
  getReconcileIntervalSec,
  setReconcileIntervalSec,
  type ReconcileIntervalSec,
} from '@shared/lib/reconcile-settings';

export function GlobalSection() {
  const [monitorAlertsEnabled, setMonitorAlertsEnabled] = useState(() => {
    return localStorage.getItem('emsx_monitor_alerts_enabled') !== 'false';
  });
  const [desktopNotificationsEnabled, setDesktopNotificationsEnabled] = useState(() => {
    return localStorage.getItem('emsx_desktop_notifications') === 'true';
  });
  const [reconcileIntervalSec, setReconcileIntervalSecState] = useState<ReconcileIntervalSec>(() =>
    getReconcileIntervalSec(),
  );

  useEffect(() => {
    localStorage.setItem('emsx_monitor_alerts_enabled', String(monitorAlertsEnabled));
  }, [monitorAlertsEnabled]);

  useEffect(() => {
    localStorage.setItem('emsx_desktop_notifications', String(desktopNotificationsEnabled));
    if (desktopNotificationsEnabled && 'Notification' in window) {
      Notification.requestPermission();
    }
  }, [desktopNotificationsEnabled]);

  return (
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
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <RefreshCw className="h-4 w-4 text-muted-foreground" />
            <div>
              <Label htmlFor="reconcile-interval" className="font-medium">Background Refresh Interval</Label>
              <p className="text-xs text-muted-foreground">How often the table cross-checks the realtime stream against the backend. Lower = fresher, more network.</p>
            </div>
          </div>
          <Select
            value={String(reconcileIntervalSec)}
            onValueChange={(v) => {
              const sec = parseInt(v, 10) as ReconcileIntervalSec;
              setReconcileIntervalSecState(sec);
              setReconcileIntervalSec(sec);
            }}
          >
            <SelectTrigger id="reconcile-interval" className="h-8 w-44 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {RECONCILE_INTERVAL_OPTIONS.map((opt) => (
                <SelectItem key={opt.value} value={String(opt.value)} className="text-xs">
                  {opt.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </CardContent>
    </Card>
  );
}
