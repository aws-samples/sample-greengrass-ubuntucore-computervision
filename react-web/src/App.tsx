import React from 'react';
import {
  BrowserRouter as Router,
  Routes,
  Route,
  Navigate,
} from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import { AuthGuard } from './components/auth/AuthGuard';
import { LoginForm } from './components/auth/LoginForm';
import ErrorBoundary from './components/common/ErrorBoundary';
import AWSErrorBoundary from './components/common/AWSErrorBoundary';
// import { Button } from './components/common/Button'; // Unused for now
import './App.css';

import { Dashboard } from './components/dashboard/Dashboard';

// Login page component
const LoginPage: React.FC = () => {
  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background:
          'linear-gradient(135deg, var(--color-surface) 0%, var(--color-background) 100%)',
      }}
    >
      <LoginForm
        onSuccess={() => {
          // Navigation will be handled by React Router
          console.log('Login successful, redirecting to dashboard');
        }}
      />
    </div>
  );
};

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Router>
          {/* Skip to main content link for keyboard navigation */}
          <a href="#main-content" className="skip-to-main">
            Skip to main content
          </a>
          <div className="App">
            <Routes>
              {/* Public login route */}
              <Route
                path="/login"
                element={
                  <AWSErrorBoundary serviceName="Authentication">
                    <LoginPage />
                  </AWSErrorBoundary>
                }
              />

              {/* Protected dashboard route */}
              <Route
                path="/dashboard"
                element={
                  <AuthGuard>
                    <AWSErrorBoundary serviceName="Dashboard">
                      <Dashboard />
                    </AWSErrorBoundary>
                  </AuthGuard>
                }
              />

              {/* Default route - redirect to dashboard (will show login if not authenticated) */}
              <Route path="/" element={<Navigate to="/dashboard" replace />} />

              {/* Catch-all route */}
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </div>
        </Router>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
