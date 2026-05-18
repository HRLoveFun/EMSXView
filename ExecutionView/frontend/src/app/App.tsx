// Platform Shell — Provider nesting entry point
// Only wraps providers; all layout logic lives in AppShell.tsx
import { AuthProvider } from './providers/AuthProvider';
import { ToastProvider } from './providers/ToastProvider';
import { RealtimeProvider } from './providers/RealtimeProvider';
import { HandoffContractsProvider } from '@shared/hooks/use-handoff-contracts';
import { AppShell } from './AppShell';
import '../App.css';

function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <RealtimeProvider>
          <HandoffContractsProvider>
            <AppShell />
          </HandoffContractsProvider>
        </RealtimeProvider>
      </ToastProvider>
    </AuthProvider>
  );
}

export default App;