/**
 * IoT Policy Service - Handles AWS IoT policy attachment for Cognito users
 * Automatically attaches IoT policies to authenticated users for MQTT access
 */

import { IoTClient, AttachPolicyCommand } from '@aws-sdk/client-iot';
import { config } from '../utils/config';

export class IoTPolicyService {
  private iotClient: IoTClient;

  constructor() {
    this.iotClient = new IoTClient({
      region: config.aws.region,
    });
  }

  /**
   * Attach IoT policy to Cognito identity
   */
  async attachPolicyToIdentity(identityId: string, credentials: any): Promise<void> {
    const policyName = config.aws.iot?.policyName;
    
    console.log('IoT Policy Attachment - Starting process');
    console.log('Config check - IoT policy name:', policyName || 'NOT CONFIGURED');
    console.log('Target identity ID:', identityId);
    
    if (!policyName) {
      console.warn('No IoT policy name configured - skipping policy attachment');
      console.warn('Make sure REACT_APP_IOT_POLICY_NAME is set in your .env.local file');
      return;
    }

    try {
      console.log('Attaching IoT policy to principal:', identityId);
      console.log('Policy name:', policyName);
      console.log('Region:', config.aws.region);

      // Create IoT client with the user's credentials
      console.log('Creating authenticated IoT client...');
      const authenticatedIoTClient = new IoTClient({
        region: config.aws.region,
        credentials: credentials,
      });

      console.log('Creating AttachPolicy command...');
      const command = new AttachPolicyCommand({
        policyName: policyName,
        target: identityId,
      });

      console.log('Sending AttachPolicy command to AWS IoT...');
      await authenticatedIoTClient.send(command);
      
      console.log('IoT policy attached successfully');
      console.log('MQTT should now work with proper authorization');
    } catch (error: any) {
      console.error('IoT policy attachment error occurred');
      console.error('Error name:', error.name);
      console.error('Error message:', error.message);
      console.error('Error code:', error.code);
      console.error('Full error object:', error);
      
      // Don't fail authentication if policy attachment fails
      if (error.name === 'ResourceAlreadyExistsException' || 
          error.message?.includes('already attached')) {
        console.log('IoT policy already attached to principal - this is OK');
      } else {
        console.warn('Failed to attach IoT policy - MQTT may not work');
        console.warn('Check your IAM permissions for iot:AttachPolicy');
        throw error; // Re-throw to see the error in the auth service logs
      }
    }
  }

  /**
   * Get Cognito Identity ID from credentials
   */
  async getIdentityId(credentials: any): Promise<string | null> {
    console.log('Getting Identity ID from credentials...');
    console.log('Credentials type:', typeof credentials);
    console.log('Credentials is function:', typeof credentials === 'function');
    
    try {
      // For fromCognitoIdentityPool credentials, we need to resolve them first
      if (typeof credentials === 'function') {
        console.log('Resolving credentials function...');
        const resolvedCredentials = await credentials();
        console.log('Resolved credentials keys:', Object.keys(resolvedCredentials || {}));
        console.log('Has identityId:', !!resolvedCredentials?.identityId);
        
        // The resolved credentials should have identityId
        if (resolvedCredentials.identityId) {
          console.log('Found identityId in resolved credentials');
          return resolvedCredentials.identityId;
        }
        
        // If not directly available, try to extract from the credentials provider
        if (resolvedCredentials.credentialProvider) {
          console.log('Trying credentialProvider...');
          const providerCreds = await resolvedCredentials.credentialProvider();
          console.log('Provider credentials keys:', Object.keys(providerCreds || {}));
          return providerCreds.identityId || null;
        }
      }
      
      // Direct credentials object
      if (credentials && credentials.identityId) {
        console.log('Found identityId in direct credentials');
        return credentials.identityId;
      }
      
      console.warn('Could not extract Identity ID from credentials object');
      console.warn('Available credential keys:', Object.keys(credentials || {}));
      return null;
    } catch (error) {
      console.error('Failed to get identity ID:', error);
      return null;
    }
  }
}

// Export singleton instance
export const iotPolicyService = new IoTPolicyService();