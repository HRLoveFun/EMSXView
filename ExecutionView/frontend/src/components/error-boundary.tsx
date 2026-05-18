/**
 * ErrorBoundary — catches React rendering errors and shows a fallback UI
 * instead of crashing the entire page (white/black screen of death).
 *
 * The project previously had NO error boundary, meaning ANY unhandled JS
 * exception in a component would unmount the whole React tree and leave the
 * user staring at a blank page. This component ensures that at worst a
 * single panel or dialog goes down while the rest of the app survives.
 *
 * Usage:
 *   <ErrorBoundary>
 *     <BatchRouteOrderDialog ... />
 *   </ErrorBoundary>
 *
 * Or wrap the entire app:
 *   <ErrorBoundary>
 *     <App />
 *   </ErrorBoundary>
 */

import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';

interface Props {
  children: ReactNode;
  /** Optional human-readable label for the faulty region (e.g. "Batch Route Dialog"). */
  label?: string;
  /** Called when an error is caught — useful for logging to remote telemetry. */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // Log to console in dev; wire to telemetry in production.
    console.error(`[ErrorBoundary${this.props.label ? ` – ${this.props.label}` : ''}]`, error, errorInfo.componentStack);
    this.props.onError?.(error, errorInfo);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      return (
        <div
          role="alert"
          className="flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-6 text-center"
        >
          <AlertTriangle className="h-8 w-8 text-destructive" />
          <div className="text-sm font-semibold text-destructive">
            {this.props.label || 'This area'} encountered an error
          </div>
          <div className="max-w-md text-xs text-muted-foreground">
            {this.state.error?.message || 'Unknown error'}
          </div>
          <button
            type="button"
            onClick={this.handleRetry}
            className="inline-flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <RefreshCw className="h-3 w-3" />
            Retry
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}