/**
 * Authentication Context for managing auth state across the application
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useCallback,
} from 'react';
import { authService } from '../services/authService';
import { discoveryService } from '../services/discoveryService';
import {
  AuthState,
  CognitoUser,
  AuthError,
  SignInCredentials,
  NewPasswordChallenge,
  AuthContextValue,
  AuthProviderProps,
} from '../types/auth';

// Auth reducer actions
type AuthAction =
  | { type: 'SET_LOADING' }
  | { type: 'SET_AUTHENTICATED'; payload: CognitoUser }
  | { type: 'SET_UNAUTHENTICATED' }
  | {
      type: 'SET_CHALLENGE_REQUIRED';
      payload: { user: CognitoUser; session: string };
    }
  | { type: 'SET_ERROR'; payload: AuthError }
  | { type: 'CLEAR_ERROR' };

// Auth state interface
interface AuthStateType {
  authState: AuthState;
  user: CognitoUser | null;
  error: AuthError | null;
  challengeSession: string | null;
}

// Initial state
const initialState: AuthStateType = {
  authState: AuthState.LOADING,
  user: null,
  error: null,
  challengeSession: null,
};

// Auth reducer
function authReducer(state: AuthStateType, action: AuthAction): AuthStateType {
  switch (action.type) {
    case 'SET_LOADING':
      return {
        ...state,
        authState: AuthState.LOADING,
        error: null,
      };

    case 'SET_AUTHENTICATED':
      return {
        ...state,
        authState: AuthState.AUTHENTICATED,
        user: action.payload,
        error: null,
        challengeSession: null,
      };

    case 'SET_UNAUTHENTICATED':
      return {
        ...state,
        authState: AuthState.UNAUTHENTICATED,
        user: null,
        error: null,
        challengeSession: null,
      };

    case 'SET_CHALLENGE_REQUIRED':
      return {
        ...state,
        authState: AuthState.CHALLENGE_REQUIRED,
        user: action.payload.user,
        challengeSession: action.payload.session,
        error: null,
      };

    case 'SET_ERROR':
      return {
        ...state,
        error: action.payload,
        authState:
          state.authState === AuthState.LOADING
            ? AuthState.UNAUTHENTICATED
            : state.authState,
      };

    case 'CLEAR_ERROR':
      return {
        ...state,
        error: null,
      };

    default:
      return state;
  }
}

// Create context
const AuthContext = createContext<AuthContextValue | undefined>(undefined);

// Auth provider component
export const AuthProvider: React.FC<AuthProviderProps> = ({ children }) => {
  const [state, dispatch] = useReducer(authReducer, initialState);

  // Initialize authentication state
  useEffect(() => {
    const initializeAuth = async () => {
      console.log('Initializing authentication state...');

      try {
        dispatch({ type: 'SET_LOADING' });

        const currentUser = await authService.getCurrentUser();

        if (currentUser) {
          console.log(
            'Found existing authenticated user:',
            currentUser.username
          );
          dispatch({ type: 'SET_AUTHENTICATED', payload: currentUser });

          // Trigger service discovery for authenticated user
          try {
            await discoveryService.getDefaultConfiguration();
            console.log(
              'Service discovery completed during auth initialization'
            );
          } catch (discoveryError) {
            console.warn(
              'Service discovery failed during auth initialization:',
              discoveryError
            );
            // Don't fail auth initialization if discovery fails
          }
        } else {
          console.log('No authenticated user found');
          dispatch({ type: 'SET_UNAUTHENTICATED' });
        }
      } catch (error) {
        console.error('Auth initialization failed:', error);
        dispatch({
          type: 'SET_ERROR',
          payload: {
            code: 'INIT_ERROR',
            message: 'Failed to initialize authentication',
            originalError: error instanceof Error ? error : undefined,
          },
        });
        dispatch({ type: 'SET_UNAUTHENTICATED' });
      }
    };

    initializeAuth();
  }, []);

  // Sign in function
  const signIn = useCallback(async (credentials: SignInCredentials) => {
    console.log('Attempting sign-in for user:', credentials.username);

    try {
      dispatch({ type: 'SET_LOADING' });
      dispatch({ type: 'CLEAR_ERROR' });

      const result = await authService.signIn(
        credentials.username,
        credentials.password
      );

      if (result.challengeName === 'NEW_PASSWORD_REQUIRED') {
        console.log('New password challenge required');
        dispatch({
          type: 'SET_CHALLENGE_REQUIRED',
          payload: {
            user: result.user,
            session: result.session || '',
          },
        });
      } else {
        console.log('Sign-in successful for user:', result.user.username);
        dispatch({ type: 'SET_AUTHENTICATED', payload: result.user });
      }
    } catch (error) {
      console.error('Sign-in failed:', error);

      const authError: AuthError = {
        code: 'SIGN_IN_ERROR',
        message: error instanceof Error ? error.message : 'Sign-in failed',
        originalError: error instanceof Error ? error : undefined,
      };

      dispatch({ type: 'SET_ERROR', payload: authError });
      dispatch({ type: 'SET_UNAUTHENTICATED' });
    }
  }, []);

  // Sign out function
  const signOut = useCallback(async () => {
    console.log('Signing out user...');

    try {
      dispatch({ type: 'SET_LOADING' });

      await authService.signOut();

      console.log('Sign-out successful');
      dispatch({ type: 'SET_UNAUTHENTICATED' });
    } catch (error) {
      console.error('Sign-out failed:', error);

      // Even if sign-out fails, clear local state
      dispatch({ type: 'SET_UNAUTHENTICATED' });

      const authError: AuthError = {
        code: 'SIGN_OUT_ERROR',
        message: 'Sign-out completed with warnings',
        originalError: error instanceof Error ? error : undefined,
      };

      dispatch({ type: 'SET_ERROR', payload: authError });
    }
  }, []);

  // Complete new password challenge
  const completeNewPassword = useCallback(
    async (challenge: NewPasswordChallenge) => {
      console.log('Completing new password challenge...');

      try {
        dispatch({ type: 'SET_LOADING' });
        dispatch({ type: 'CLEAR_ERROR' });

        const result = await authService.completeNewPassword(
          challenge.newPassword,
          challenge.session,
          state.user?.username
        );

        console.log(
          'New password challenge completed for user:',
          result.user.username
        );
        dispatch({ type: 'SET_AUTHENTICATED', payload: result.user });
      } catch (error) {
        console.error('New password challenge failed:', error);

        const authError: AuthError = {
          code: 'NEW_PASSWORD_ERROR',
          message:
            error instanceof Error
              ? error.message
              : 'Failed to set new password',
          originalError: error instanceof Error ? error : undefined,
        };

        dispatch({ type: 'SET_ERROR', payload: authError });
        // Stay in challenge state to allow retry
      }
    },
    [state.user?.username]
  );

  // Clear error function
  const clearError = useCallback(() => {
    dispatch({ type: 'CLEAR_ERROR' });
  }, []);

  // Context value
  const contextValue: AuthContextValue = {
    user: state.user,
    authState: state.authState,
    error: state.error,
    challengeSession: state.challengeSession,
    signIn,
    signOut,
    completeNewPassword,
    clearError,
    isAuthenticated: state.authState === AuthState.AUTHENTICATED,
  };

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  );
};

// Custom hook to use auth context
export const useAuth = (): AuthContextValue => {
  const context = useContext(AuthContext);

  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }

  return context;
};

// Export context for testing
export { AuthContext };
