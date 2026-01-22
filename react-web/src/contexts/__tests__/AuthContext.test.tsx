/**
 * Tests for AuthContext
 */

import React from 'react';
import { render, screen, act } from '@testing-library/react';
import { AuthProvider, useAuth } from '../AuthContext';
import { AuthState } from '../../types/auth';

// Mock the auth service
jest.mock('../../services/authService', () => ({
  authService: {
    getCurrentUser: jest.fn().mockResolvedValue(null),
    signIn: jest.fn(),
    signOut: jest.fn(),
    completeNewPassword: jest.fn(),
  },
}));

// Mock the discovery service
jest.mock('../../services/discoveryService', () => ({
  discoveryService: {
    getDefaultConfiguration: jest.fn().mockResolvedValue({
      iotEndpoint: 'test-endpoint',
      s3BucketName: 'test-bucket',
      mqttTopic: 'test/topic',
      region: 'eu-west-1',
    }),
  },
}));

// Mock the config
jest.mock('../../utils/config', () => ({
  config: {
    aws: {
      region: 'eu-west-1',
      cognito: {
        userPoolId: 'eu-west-1_test123',
        clientId: 'test-client-id',
        identityPoolId: 'eu-west-1:test-identity-pool-id',
      },
    },
    services: {
      s3BucketName: undefined,
      mqttTopic: undefined,
    },
  },
}));

// Test component that uses the auth context
const TestComponent: React.FC = () => {
  const { authState, user, isAuthenticated } = useAuth();

  return (
    <div>
      <div data-testid="auth-state">{authState}</div>
      <div data-testid="user">{user?.username || 'No user'}</div>
      <div data-testid="is-authenticated">{isAuthenticated.toString()}</div>
    </div>
  );
};

describe('AuthContext', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('should provide initial unauthenticated state', async () => {
    await act(async () => {
      render(
        <AuthProvider>
          <TestComponent />
        </AuthProvider>
      );
    });

    expect(screen.getByTestId('auth-state')).toHaveTextContent(
      AuthState.UNAUTHENTICATED
    );
    expect(screen.getByTestId('user')).toHaveTextContent('No user');
    expect(screen.getByTestId('is-authenticated')).toHaveTextContent('false');
  });

  test('should throw error when useAuth is used outside provider', () => {
    // Suppress console.error for this test
    const consoleSpy = jest
      .spyOn(console, 'error')
      .mockImplementation(() => {});

    expect(() => {
      render(<TestComponent />);
    }).toThrow('useAuth must be used within an AuthProvider');

    consoleSpy.mockRestore();
  });
});
