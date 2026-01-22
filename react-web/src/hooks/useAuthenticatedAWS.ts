/**
 * Hook for accessing authenticated AWS services
 */

import { useContext, useMemo } from 'react';
import { AuthContext } from '../contexts/AuthContext';
import { authService } from '../services/authService';
import { config } from '../utils/config';
import { AuthState } from '../types/auth';

export const useAuthenticatedAWS = () => {
  const authContext = useContext(AuthContext);

  if (!authContext) {
    throw new Error('useAuthenticatedAWS must be used within an AuthProvider');
  }

  const { authState, user } = authContext;

  // Create AWS credentials only when authenticated
  const credentials = useMemo(() => {
    if (authState !== AuthState.AUTHENTICATED || !user) {
      return null;
    }

    console.log(
      'Creating authenticated AWS credentials for user:',
      user.username
    );

    try {
      // Use the authService's method which properly includes the ID token
      return authService.getAWSCredentials();
    } catch (error) {
      console.error('Failed to get AWS credentials:', error);
      return null;
    }
  }, [authState, user]);

  return {
    credentials,
    isAuthenticated: authState === AuthState.AUTHENTICATED,
    user,
    region: config.aws.region,
  };
};
