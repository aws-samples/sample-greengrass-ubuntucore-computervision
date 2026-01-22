import React from 'react';
import { render, screen } from '@testing-library/react';
import { LoginForm } from './components/auth/LoginForm';

// Mock the auth service
jest.mock('./services/authService', () => ({
  authService: {
    getCurrentUser: jest.fn().mockResolvedValue(null),
    signIn: jest.fn(),
    signOut: jest.fn(),
    completeNewPassword: jest.fn(),
  },
}));

// Mock the discovery service
jest.mock('./services/discoveryService', () => ({
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
jest.mock('./utils/config', () => ({
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

// Mock the auth context
jest.mock('./contexts/AuthContext', () => ({
  useAuth: () => ({
    signIn: jest.fn(),
    authState: 'unauthenticated',
    error: null,
    clearError: jest.fn(),
  }),
}));

test('renders login form with Sign In title', () => {
  render(<LoginForm />);
  expect(screen.getByRole('heading', { name: /Sign In/i })).toBeInTheDocument();
});

test('renders AWS logo in login form', () => {
  render(<LoginForm />);
  const logoElement = screen.getByAltText(/AWS Logo/i);
  expect(logoElement).toBeInTheDocument();
});

test('renders username and password fields', () => {
  render(<LoginForm />);
  expect(screen.getByLabelText(/Username/i)).toBeInTheDocument();
  expect(screen.getByLabelText(/Password/i)).toBeInTheDocument();
});
