/**
 * Configuration utility for loading and validating environment variables
 */

export interface AppConfig {
  aws: {
    region: string;
    cognito: {
      userPoolId: string;
      clientId: string;
      identityPoolId: string;
    };
    iot?: {
      policyName?: string;
    };
  };
  services: {
    s3BucketName?: string;
    mqttTopic?: string;
  };
}

/**
 * Gets environment variables in a browser-compatible way
 */
function getEnvVar(name: string): string | undefined {
  // In Vite, environment variables are available through import.meta.env
  if (typeof import.meta !== 'undefined' && import.meta.env) {
    return import.meta.env[name];
  }
  
  // Fallback for Node.js environment (testing, etc.)
  if (typeof process !== 'undefined' && process.env) {
    return process.env[name];
  }
  
  // Fallback for other bundlers
  if (typeof window !== 'undefined') {
    return (window as any).__ENV__?.[name];
  }
  
  return undefined;
}

/**
 * Validates that a required environment variable is present
 */
function requireEnvVar(name: string): string {
  const value = getEnvVar(name);
  if (!value) {
    throw new Error(
      `Missing required environment variable: ${name}. Please check your .env.local file.`
    );
  }
  return value;
}

/**
 * Gets an optional environment variable
 */
function getOptionalEnvVar(name: string): string | undefined {
  return getEnvVar(name) || undefined;
}

/**
 * Validates AWS region format
 */
function validateAwsRegion(region: string): void {
  const regionPattern = /^[a-z]{2}-[a-z]+-\d+$/;
  if (!regionPattern.test(region)) {
    throw new Error(
      `Invalid AWS region format: ${region}. Expected format: us-east-1, eu-west-1, etc.`
    );
  }
}

/**
 * Validates Cognito User Pool ID format
 */
function validateUserPoolId(userPoolId: string): void {
  const userPoolPattern = /^[a-z0-9-]+_[a-zA-Z0-9]+$/;
  if (!userPoolPattern.test(userPoolId)) {
    throw new Error(
      `Invalid Cognito User Pool ID format: ${userPoolId}. Expected format: us-east-1_xxxxxxxxx`
    );
  }
}

/**
 * Validates Cognito Identity Pool ID format
 */
function validateIdentityPoolId(identityPoolId: string): void {
  const identityPoolPattern = /^[a-z0-9-]+:[a-f0-9-]{36}$/;
  if (!identityPoolPattern.test(identityPoolId)) {
    throw new Error(
      `Invalid Cognito Identity Pool ID format: ${identityPoolId}. Expected format: us-east-1:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
    );
  }
}

/**
 * Loads and validates application configuration from environment variables
 */
export function loadConfig(): AppConfig {
  try {
    // Required configuration
    const region = requireEnvVar('REACT_APP_AWS_REGION');
    const userPoolId = requireEnvVar('REACT_APP_COGNITO_USER_POOL_ID');
    const clientId = requireEnvVar('REACT_APP_COGNITO_CLIENT_ID');
    const identityPoolId = requireEnvVar('REACT_APP_COGNITO_IDENTITY_POOL_ID');

    // Validate required configuration
    validateAwsRegion(region);
    validateUserPoolId(userPoolId);
    validateIdentityPoolId(identityPoolId);

    // Optional configuration
    const s3BucketName = getOptionalEnvVar('REACT_APP_S3_BUCKET_NAME');
    const mqttTopic = getOptionalEnvVar('REACT_APP_MQTT_TOPIC');
    const iotPolicyName = getOptionalEnvVar('REACT_APP_IOT_POLICY_NAME');

    const config: AppConfig = {
      aws: {
        region,
        cognito: {
          userPoolId,
          clientId,
          identityPoolId,
        },
        iot: iotPolicyName ? {
          policyName: iotPolicyName,
        } : undefined,
      },
      services: {
        s3BucketName,
        mqttTopic,
      },
    };

    console.log('Configuration loaded successfully:', {
      region: config.aws.region,
      userPoolId: config.aws.cognito.userPoolId,
      hasS3BucketName: !!config.services.s3BucketName,
      hasMqttTopic: !!config.services.mqttTopic,
    });

    return config;
  } catch (error) {
    console.error('Configuration error:', error);
    throw error;
  }
}

/**
 * Global configuration instance
 */
export const config = loadConfig();
