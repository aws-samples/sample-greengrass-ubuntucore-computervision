/**
 * TypeScript interfaces for AWS Service Discovery
 */

export interface ServiceConfiguration {
  iotEndpoint: string;
  s3BucketName: string;
  mqttTopic: string;
  region: string;
}

export interface DiscoveryCache {
  iotEndpoint?: string;
  s3Buckets?: string[];
  timestamp: number;
  expiresAt: number;
}

export interface DiscoveryError {
  service: 'iot' | 's3' | 'general';
  message: string;
  originalError?: Error;
}

export interface DiscoveryResult<T> {
  success: boolean;
  data?: T;
  error?: DiscoveryError;
  fromCache?: boolean;
}

export interface S3BucketInfo {
  name: string;
  region?: string;
  creationDate?: Date;
}

export interface IoTEndpointInfo {
  address: string;
  type: string;
  region: string;
}

export interface DiscoveryOptions {
  useCache?: boolean;
  timeout?: number;
  retryAttempts?: number;
}

export interface ServiceDiscoveryState {
  isDiscovering: boolean;
  lastDiscovery?: Date;
  configuration?: ServiceConfiguration;
  errors: DiscoveryError[];
}
