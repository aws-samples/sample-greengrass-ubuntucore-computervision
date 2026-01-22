/**
 * Authentication Service using Amazon Cognito
 * Handles user authentication, session management, and credential provisioning
 */

import {
  CognitoIdentityProviderClient,
  InitiateAuthCommand,
  RespondToAuthChallengeCommand,
  GlobalSignOutCommand,
  GetUserCommand,
  AuthFlowType,
  ChallengeNameType,
} from '@aws-sdk/client-cognito-identity-provider';
import { fromCognitoIdentityPool } from '@aws-sdk/credential-providers';
import { config } from '../utils/config';
import { discoveryService } from './discoveryService';
import { iotPolicyService } from './iotPolicyService';

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

const SESSION_KEY = 'cognito-auth-session';
const TOKEN_REFRESH_THRESHOLD = 5 * 60 * 1000; // 5 minutes before expiry

export class AuthService {
  private cognitoClient: CognitoIdentityProviderClient;
  private currentSession: AuthSession | null = null;
  private refreshTimer: NodeJS.Timeout | null = null;

  constructor() {
    this.cognitoClient = new CognitoIdentityProviderClient({
      region: config.aws.region,
    });

    // Load existing session on initialization
    this.loadStoredSession();
  }

  /**
   * Load stored session from localStorage
   */
  private loadStoredSession(): void {
    try {
      const stored = localStorage.getItem(SESSION_KEY);
      if (!stored) return;

      const session: AuthSession = JSON.parse(stored);

      // Check if session is expired
      if (Date.now() >= session.expiresAt) {
        console.log('Stored session expired, clearing...');
        this.clearStoredSession();
        return;
      }

      this.currentSession = session;
      this.scheduleTokenRefresh();
      console.log(
        'Loaded existing auth session for user:',
        session.user.username
      );
    } catch (error) {
      console.warn('Failed to load stored session:', error);
      this.clearStoredSession();
    }
  }

  /**
   * Store session in localStorage
   */
  private storeSession(session: AuthSession): void {
    try {
      localStorage.setItem(SESSION_KEY, JSON.stringify(session));
      console.log('Auth session stored successfully');
    } catch (error) {
      console.warn('Failed to store auth session:', error);
    }
  }

  /**
   * Clear stored session
   */
  private clearStoredSession(): void {
    localStorage.removeItem(SESSION_KEY);
    this.currentSession = null;
    if (this.refreshTimer) {
      clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
  }

  /**
   * Schedule automatic token refresh
   */
  private scheduleTokenRefresh(): void {
    if (!this.currentSession || this.refreshTimer) return;

    const timeUntilRefresh =
      this.currentSession.expiresAt - Date.now() - TOKEN_REFRESH_THRESHOLD;

    if (timeUntilRefresh > 0) {
      this.refreshTimer = setTimeout(() => {
        this.refreshTokens();
      }, timeUntilRefresh);

      console.log(
        `Token refresh scheduled in ${Math.round(timeUntilRefresh / 1000 / 60)} minutes`
      );
    }
  }

  /**
   * Refresh authentication tokens
   */
  private async refreshTokens(): Promise<void> {
    if (!this.currentSession?.refreshToken) {
      console.warn('No refresh token available');
      return;
    }

    try {
      console.log('Refreshing authentication tokens...');

      const command = new InitiateAuthCommand({
        AuthFlow: AuthFlowType.REFRESH_TOKEN_AUTH,
        ClientId: config.aws.cognito.clientId,
        AuthParameters: {
          REFRESH_TOKEN: this.currentSession.refreshToken,
        },
      });

      const response = await this.cognitoClient.send(command);

      if (response.AuthenticationResult) {
        const { AccessToken, IdToken, ExpiresIn } =
          response.AuthenticationResult;

        if (AccessToken && IdToken) {
          // Update current session with new tokens
          this.currentSession.accessToken = AccessToken;
          this.currentSession.idToken = IdToken;
          this.currentSession.expiresAt =
            Date.now() + (ExpiresIn || 3600) * 1000;

          this.storeSession(this.currentSession);
          this.scheduleTokenRefresh();

          console.log('Tokens refreshed successfully');
        }
      }
    } catch (error) {
      console.error('Token refresh failed:', error);
      // If refresh fails, clear session and require re-authentication
      this.clearStoredSession();
    }
  }

  /**
   * Parse user attributes from Cognito response
   */
  private parseUserAttributes(attributes: any[]): Record<string, string> {
    const parsed: Record<string, string> = {};

    if (Array.isArray(attributes)) {
      attributes.forEach((attr) => {
        if (attr.Name && attr.Value) {
          parsed[attr.Name] = attr.Value;
        }
      });
    }

    return parsed;
  }

  /**
   * Create CognitoUser from authentication result
   */
  private async createCognitoUser(accessToken: string): Promise<CognitoUser> {
    try {
      const getUserCommand = new GetUserCommand({
        AccessToken: accessToken,
      });

      const userResponse = await this.cognitoClient.send(getUserCommand);
      const attributes = this.parseUserAttributes(
        userResponse.UserAttributes || []
      );

      return {
        username: userResponse.Username || '',
        email: attributes['email'],
        attributes,
      };
    } catch (error) {
      console.error('Failed to get user details:', error);
      throw new Error('Failed to retrieve user information');
    }
  }

  /**
   * Sign in with username and password
   */
  async signIn(username: string, password: string): Promise<AuthResult> {
    console.log(`Attempting sign-in for user: ${username}`);

    try {
      const command = new InitiateAuthCommand({
        AuthFlow: AuthFlowType.USER_PASSWORD_AUTH,
        ClientId: config.aws.cognito.clientId,
        AuthParameters: {
          USERNAME: username,
          PASSWORD: password,
        },
      });

      const response = await this.cognitoClient.send(command);

      // Handle successful authentication
      if (response.AuthenticationResult) {
        const { AccessToken, IdToken, RefreshToken, ExpiresIn } =
          response.AuthenticationResult;

        if (!AccessToken || !IdToken) {
          throw new Error('Missing authentication tokens');
        }

        const user = await this.createCognitoUser(AccessToken);

        // Create and store session
        const session: AuthSession = {
          accessToken: AccessToken,
          idToken: IdToken,
          refreshToken: RefreshToken || '',
          user,
          expiresAt: Date.now() + (ExpiresIn || 3600) * 1000,
        };

        this.currentSession = session;
        this.storeSession(session);
        this.scheduleTokenRefresh();

        console.log('Sign-in successful for user:', user.username);

        // Trigger service discovery after successful authentication
        try {
          await discoveryService.getDefaultConfiguration();
          console.log('Service discovery completed after authentication');
        } catch (discoveryError) {
          console.warn(
            'Service discovery failed after authentication:',
            discoveryError
          );
          // Don't fail authentication if discovery fails
        }

        // Attach IoT policy for MQTT access
        try {
          console.log('Starting IoT policy attachment process...');
          const awsCredentials = this.getAWSCredentials();
          console.log('AWS credentials obtained for IoT policy attachment');
          
          const identityId = await iotPolicyService.getIdentityId(awsCredentials);
          console.log('Identity ID retrieved:', identityId ? `***${identityId.slice(-8)}` : 'null');
          
          if (identityId) {
            await iotPolicyService.attachPolicyToIdentity(identityId, awsCredentials);
            console.log('IoT policy attachment process completed');
          } else {
            console.warn('Could not get Cognito Identity ID for IoT policy attachment');
          }
        } catch (iotError) {
          console.error('IoT policy attachment failed:', iotError);
          console.error('IoT policy attachment error details:', {
            name: iotError?.name,
            message: iotError?.message,
            code: iotError?.code
          });
          // Don't fail authentication if IoT policy attachment fails
        }

        return {
          user,
          accessToken: AccessToken,
          idToken: IdToken,
          refreshToken: RefreshToken,
        };
      }

      // Handle authentication challenges
      if (response.ChallengeName) {
        console.log(
          'Authentication challenge required:',
          response.ChallengeName
        );

        return {
          user: { username, attributes: {} },
          challengeName: response.ChallengeName,
          session: response.Session,
        };
      }

      throw new Error('Unexpected authentication response');
    } catch (error) {
      console.error('Sign-in failed:', error);

      if (error instanceof Error) {
        // Handle specific Cognito errors
        if (error.name === 'NotAuthorizedException') {
          throw new Error('Invalid username or password');
        } else if (error.name === 'UserNotConfirmedException') {
          throw new Error('User account not confirmed');
        } else if (error.name === 'PasswordResetRequiredException') {
          throw new Error('Password reset required');
        } else if (error.name === 'UserNotFoundException') {
          throw new Error('User not found');
        } else if (error.name === 'TooManyRequestsException') {
          throw new Error('Too many requests. Please try again later');
        }
      }

      throw new Error('Sign-in failed. Please try again');
    }
  }

  /**
   * Complete new password challenge
   */
  async completeNewPassword(
    newPassword: string,
    session: string,
    username?: string
  ): Promise<AuthResult> {
    console.log('Completing new password challenge...');

    try {
      const command = new RespondToAuthChallengeCommand({
        ClientId: config.aws.cognito.clientId,
        ChallengeName: ChallengeNameType.NEW_PASSWORD_REQUIRED,
        Session: session,
        ChallengeResponses: {
          NEW_PASSWORD: newPassword,
          USERNAME: username || this.currentSession?.user.username || '',
        },
      });

      const response = await this.cognitoClient.send(command);

      if (response.AuthenticationResult) {
        const { AccessToken, IdToken, RefreshToken, ExpiresIn } =
          response.AuthenticationResult;

        if (!AccessToken || !IdToken) {
          throw new Error('Missing authentication tokens');
        }

        const user = await this.createCognitoUser(AccessToken);

        // Create and store session
        const authSession: AuthSession = {
          accessToken: AccessToken,
          idToken: IdToken,
          refreshToken: RefreshToken || '',
          user,
          expiresAt: Date.now() + (ExpiresIn || 3600) * 1000,
        };

        this.currentSession = authSession;
        this.storeSession(authSession);
        this.scheduleTokenRefresh();

        console.log('New password challenge completed successfully');

        // Attach IoT policy for MQTT access
        try {
          const awsCredentials = this.getAWSCredentials();
          const identityId = await iotPolicyService.getIdentityId(awsCredentials);
          
          if (identityId) {
            await iotPolicyService.attachPolicyToIdentity(identityId, awsCredentials);
          } else {
            console.warn('Could not get Cognito Identity ID for IoT policy attachment');
          }
        } catch (iotError) {
          console.warn('IoT policy attachment failed:', iotError);
          // Don't fail authentication if IoT policy attachment fails
        }

        return {
          user,
          accessToken: AccessToken,
          idToken: IdToken,
          refreshToken: RefreshToken,
        };
      }

      throw new Error('Failed to complete password challenge');
    } catch (error) {
      console.error('New password challenge failed:', error);
      throw new Error('Failed to set new password. Please try again');
    }
  }

  /**
   * Sign out user
   */
  async signOut(): Promise<void> {
    console.log('Signing out user...');

    try {
      if (this.currentSession?.accessToken) {
        const command = new GlobalSignOutCommand({
          AccessToken: this.currentSession.accessToken,
        });

        await this.cognitoClient.send(command);
        console.log('Global sign-out successful');
      }
    } catch (error) {
      console.warn('Global sign-out failed:', error);
      // Continue with local sign-out even if global sign-out fails
    }

    // Clear local session
    this.clearStoredSession();

    // Clear discovery cache
    discoveryService.clearCache();

    console.log('Local sign-out completed');
  }

  /**
   * Get current user
   */
  async getCurrentUser(): Promise<CognitoUser | null> {
    if (!this.currentSession) {
      return null;
    }

    // Check if session is still valid
    if (Date.now() >= this.currentSession.expiresAt) {
      console.log('Current session expired');
      this.clearStoredSession();
      return null;
    }

    return this.currentSession.user;
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return (
      this.currentSession !== null && Date.now() < this.currentSession.expiresAt
    );
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    if (!this.isAuthenticated()) {
      return null;
    }

    return this.currentSession?.accessToken || null;
  }

  /**
   * Get AWS credentials for authenticated user
   */
  getAWSCredentials() {
    if (!this.isAuthenticated() || !this.currentSession?.idToken) {
      throw new Error('User not authenticated');
    }

    return fromCognitoIdentityPool({
      identityPoolId: config.aws.cognito.identityPoolId,
      logins: {
        [`cognito-idp.${config.aws.region}.amazonaws.com/${config.aws.cognito.userPoolId}`]:
          this.currentSession.idToken,
      },
      clientConfig: { region: config.aws.region },
    });
  }
}

// Export singleton instance
export const authService = new AuthService();
