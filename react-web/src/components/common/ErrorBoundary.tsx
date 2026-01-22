import React, { Component, ErrorInfo, ReactNode } from 'react';
import './ErrorBoundary.css';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorInfo: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);

    this.setState({
      error,
      errorInfo,
    });

    // Call custom error handler if provided
    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }

    // Log error for monitoring (could integrate with CloudWatch later)
    this.logError(error, errorInfo);
  }

  private logError = (error: Error, errorInfo: ErrorInfo) => {
    // For now, just console.error - could be enhanced to send to CloudWatch
    console.error('Error logged:', {
      message: error.message,
      stack: error.stack,
      componentStack: errorInfo.componentStack,
      timestamp: new Date().toISOString(),
    });
  };

  private handleRetry = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render() {
    if (this.state.hasError) {
      // Custom fallback UI
      if (this.props.fallback) {
        return this.props.fallback;
      }

      // Default error UI with AWS branding
      return (
        <div className="error-boundary">
          <div className="error-boundary__container">
            <div className="error-boundary__icon">
              <svg
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
              >
                <path
                  d="M12 2L1 21H23L12 2Z"
                  stroke="var(--aws-color-red-500)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M12 9V13"
                  stroke="var(--aws-color-red-500)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                <path
                  d="M12 17H12.01"
                  stroke="var(--aws-color-red-500)"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </div>

            <h2 className="error-boundary__title">Something went wrong</h2>

            <p className="error-boundary__message">
              We encountered an unexpected error. This might be due to a
              temporary issue with AWS services or a network problem.
            </p>

            <div className="error-boundary__actions">
              <button
                className="error-boundary__button error-boundary__button--primary"
                onClick={this.handleRetry}
              >
                Try Again
              </button>

              <button
                className="error-boundary__button error-boundary__button--secondary"
                onClick={() => window.location.reload()}
              >
                Reload Page
              </button>
            </div>

            {process.env.NODE_ENV === 'development' && this.state.error && (
              <details className="error-boundary__details">
                <summary>Error Details (Development Only)</summary>
                <pre className="error-boundary__error-text">
                  {this.state.error.toString()}
                  {this.state.errorInfo?.componentStack}
                </pre>
              </details>
            )}
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
