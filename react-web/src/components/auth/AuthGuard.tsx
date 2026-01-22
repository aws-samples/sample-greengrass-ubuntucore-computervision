/**
 * AuthGuard Component for protecting routes that require authentication
 */

import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../contexts/AuthContext';
import { AuthState } from '../../types/auth';
import { LoginForm } from './LoginForm';
import { PasswordResetForm } from './PasswordResetForm';

export interface AuthGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
  redirectTo?: string;
}

export const AuthGuard: React.FC<AuthGuardProps> = ({
  children,
  fallback,
  redirectTo = '/login',
}) => {
  const { authState, user, error } = useAuth();
  const location = useLocation();

  // Show loading state while checking authentication
  if (authState === AuthState.LOADING) {
    return (
      <div className="auth-guard-loading">
        <div className="loading-container">
          <div className="loading-spinner" />
          <p>Checking authentication...</p>
        </div>
      </div>
    );
  }

  // Handle new password challenge
  if (authState === AuthState.CHALLENGE_REQUIRED) {
    return (
      <div className="auth-guard-challenge">
        <PasswordResetForm
          onSuccess={() => {
            // Navigation will be handled by the auth state change
            console.log('Password reset completed, user will be redirected');
          }}
        />
      </div>
    );
  }

  // Handle unauthenticated state
  if (authState === AuthState.UNAUTHENTICATED) {
    // If a custom fallback is provided, use it
    if (fallback) {
      return <>{fallback}</>;
    }

    // If redirectTo is a path, navigate to it
    if (redirectTo !== '/login') {
      return <Navigate to={redirectTo} state={{ from: location }} replace />;
    }

    // Default: show login form
    return (
      <div className="auth-guard-login">
        <LoginForm
          onSuccess={() => {
            // Navigation will be handled by the auth state change
            console.log('Login successful, user will be redirected');
          }}
        />
      </div>
    );
  }

  // Handle authentication errors
  if (error && authState !== AuthState.AUTHENTICATED) {
    return (
      <div className="auth-guard-error">
        <div className="error-container">
          <div className="error-icon"></div>
          <h2>Authentication Error</h2>
          <p>{error.message}</p>
          <button
            onClick={() => window.location.reload()}
            className="aws-button aws-button--primary"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // User is authenticated, render protected content
  if (authState === AuthState.AUTHENTICATED && user) {
    return <>{children}</>;
  }

  // Fallback for unexpected states
  return (
    <div className="auth-guard-fallback">
      <div className="fallback-container">
        <p>Initializing application...</p>
      </div>
    </div>
  );
};
