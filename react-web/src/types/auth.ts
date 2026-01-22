/**
 * TypeScript interfaces for Authentication
 */

export interface CognitoUser {
  username: string;
  email?: string;
  attributes: Record<string, string>;
}

export interface AuthResult {
  user: CognitoUser;
  challengeName?: string;
  session?: string;
  accessToken?: string;
  idToken?: string;
  refreshToken?: string;
}

export enum AuthState {
  LOADING = 'loading',
  AUTHENTICATED = 'authenticated',
  UNAUTHENTICATED = 'unauthenticated',
  CHALLENGE_REQUIRED = 'challenge_required',
}

export interface AuthSession {
  accessToken: string;
  idToken: string;
  refreshToken: string;
  user: CognitoUser;
  expiresAt: number;
}

export interface AuthError {
  code: string;
  message: string;
  originalError?: Error;
}

export interface SignInCredentials {
  username: string;
  password: string;
}

export interface NewPasswordChallenge {
  newPassword: string;
  session: string;
}

export interface AuthContextValue {
  user: CognitoUser | null;
  authState: AuthState;
  error: AuthError | null;
  challengeSession: string | null;
  signIn: (credentials: SignInCredentials) => Promise<void>;
  signOut: () => Promise<void>;
  completeNewPassword: (challenge: NewPasswordChallenge) => Promise<void>;
  clearError: () => void;
  isAuthenticated: boolean;
}

export interface AuthProviderProps {
  children: React.ReactNode;
}

export interface AuthGuardProps {
  children: React.ReactNode;
  fallback?: React.ReactNode;
}
