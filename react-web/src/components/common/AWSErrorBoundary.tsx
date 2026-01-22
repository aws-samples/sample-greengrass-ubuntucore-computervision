import React, { ReactNode } from 'react';
import ErrorBoundary from './ErrorBoundary';

interface AWSErrorBoundaryProps {
  children: ReactNode;
  serviceName?: string;
  onRetry?: () => void;
}

const AWSErrorBoundary: React.FC<AWSErrorBoundaryProps> = ({
  children,
  serviceName = 'AWS Service',
  onRetry,
}) => {
  const handleAWSError = (error: Error) => {
    // Enhanced logging for AWS-specific errors
    console.error('AWS Service Error in:', serviceName, {
      service: serviceName,
      error: error.message,
      stack: error.stack,
      timestamp: new Date().toISOString(),
    });

    // Could integrate with AWS CloudWatch or X-Ray here
    // Example: sendToCloudWatch(error, serviceName);
  };

  const customFallback = (
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

        <h2 className="error-boundary__title">{serviceName} Error</h2>

        <p className="error-boundary__message">
          We're having trouble connecting to {serviceName}. This could be due
          to:
        </p>

        <ul
          style={{
            textAlign: 'left',
            color: 'var(--aws-color-text-body-default)',
            marginBottom: 'var(--spacing-lg)',
          }}
        >
          <li>Network connectivity issues</li>
          <li>AWS service temporary unavailability</li>
          <li>Authentication or permission problems</li>
          <li>Service configuration issues</li>
        </ul>

        <div className="error-boundary__actions">
          <button
            className="error-boundary__button error-boundary__button--primary"
            onClick={onRetry || (() => window.location.reload())}
          >
            Retry Connection
          </button>

          <button
            className="error-boundary__button error-boundary__button--secondary"
            onClick={() => window.location.reload()}
          >
            Reload Page
          </button>
        </div>
      </div>
    </div>
  );

  return (
    <ErrorBoundary fallback={customFallback} onError={handleAWSError}>
      {children}
    </ErrorBoundary>
  );
};

export default AWSErrorBoundary;
