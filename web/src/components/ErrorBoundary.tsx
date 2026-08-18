import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null });
    window.location.href = "/";
  };

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <div className="flex min-h-[60vh] items-center justify-center px-4">
        <div className="card mx-auto max-w-md animate-fade-in px-8 py-12 text-center">
          <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-red-50 text-3xl">
            ⚠️
          </div>
          <h2 className="font-display text-xl font-bold text-primary-800">
            页面出了点问题
          </h2>
          <p className="mt-2 text-sm text-sand-500">
            很抱歉，页面发生了意外错误。请尝试刷新或返回首页。
          </p>
          {import.meta.env.DEV && this.state.error && (
            <pre className="mt-4 max-h-32 overflow-auto rounded-xl bg-sand-50 p-3 text-left text-xs text-red-600">
              {this.state.error.message}
            </pre>
          )}
          <div className="mt-6 flex justify-center gap-3">
            <button
              onClick={() => window.location.reload()}
              className="btn-secondary"
            >
              刷新页面
            </button>
            <button onClick={this.handleReset} className="btn-primary">
              返回首页
            </button>
          </div>
        </div>
      </div>
    );
  }
}
