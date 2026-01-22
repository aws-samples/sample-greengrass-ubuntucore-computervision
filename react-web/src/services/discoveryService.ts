/**
 * AWS Service Discovery Service
 * Automatically discovers AWS service endpoints and resources
 */

import { IoTClient, DescribeEndpointCommand } from '@aws-sdk/client-iot';
import { authService } from './authService';
import { config } from '../utils/config';

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

const CACHE_DURATION = 1000 * 60 * 60; // 1 hour
const CACHE_KEY = 'aws-service-discovery-cache';

export class DiscoveryService {
  private iotClient: IoTClient | null = null;
  private credentials: any = null;

  /**
   * Initialize AWS clients with authenticated credentials
   */
  private async initializeClients(): Promise<void> {
    if (!this.credentials) {
      console.log('Initializing AWS credentials for service discovery...');

      // Use the authService's method which properly includes the ID token
      if (!authService.isAuthenticated()) {
        throw new Error('User must be authenticated to use discovery service');
      }

      this.credentials = authService.getAWSCredentials();
    }

    if (!this.iotClient) {
      this.iotClient = new IoTClient({
        region: config.aws.region,
        credentials: this.credentials,
      });
    }
  }

  /**
   * Get cached discovery results
   */
  private getCachedResults(): DiscoveryCache | null {
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      if (!cached) return null;

      const parsedCache: DiscoveryCache = JSON.parse(cached);

      // Check if cache is expired
      if (Date.now() > parsedCache.expiresAt) {
        localStorage.removeItem(CACHE_KEY);
        return null;
      }

      console.log('Using cached service discovery results');
      return parsedCache;
    } catch (error) {
      console.warn('Failed to read discovery cache:', error);
      localStorage.removeItem(CACHE_KEY);
      return null;
    }
  }

  /**
   * Cache discovery results
   */
  private setCachedResults(cache: Partial<DiscoveryCache>): void {
    try {
      const timestamp = Date.now();
      const cacheData: DiscoveryCache = {
        timestamp,
        expiresAt: timestamp + CACHE_DURATION,
        ...cache,
      };

      localStorage.setItem(CACHE_KEY, JSON.stringify(cacheData));
      console.log('Cached service discovery results');
    } catch (error) {
      console.warn('Failed to cache discovery results:', error);
    }
  }

  /**
   * Discover IoT Core endpoint for the current region
   */
  async discoverIoTEndpoint(region: string): Promise<string> {
    console.log('Discovering IoT Core endpoint for region:', region);

    try {
      await this.initializeClients();

      if (!this.iotClient) {
        throw new Error('IoT client not initialized');
      }

      const command = new DescribeEndpointCommand({
        endpointType: 'iot:Data-ATS',
      });

      const response = await this.iotClient.send(command);

      if (!response.endpointAddress) {
        throw new Error('No IoT endpoint address returned');
      }

      console.log('Discovered IoT endpoint:', response.endpointAddress);
      return response.endpointAddress;
    } catch (error) {
      console.error('Failed to discover IoT endpoint:', error);
      throw new Error(
        `IoT endpoint discovery failed: ${error instanceof Error ? error.message : 'Unknown error'}`
      );
    }
  }

  /**
   * Discover S3 buckets - DISABLED to avoid CORS issues
   * Use environment configuration only
   */
  async discoverS3Buckets(): Promise<string[]> {
    console.log('S3 bucket discovery disabled - using environment only');

    // Only return buckets from environment configuration
    if (config.services.s3BucketName) {
      console.log('Using configured S3 bucket:', config.services.s3BucketName);
      return [config.services.s3BucketName];
    }

    console.warn('No S3 bucket configured in environment.');
    return [];
  }

  /**
   * Get default configuration with auto-discovery
   */
  async getDefaultConfiguration(): Promise<ServiceConfiguration> {
    console.log('Getting default configuration with auto-discovery...');

    try {
      // Check cache first
      const cached = this.getCachedResults();

      let iotEndpoint: string;
      let s3BucketName: string;
      let mqttTopic: string;

      if (cached && cached.iotEndpoint && cached.s3Buckets) {
        iotEndpoint = cached.iotEndpoint;
        s3BucketName = cached.s3Buckets[0] || '';
      } else {
        // Discover services
        const [discoveredEndpoint, discoveredBuckets] = await Promise.all([
          this.discoverIoTEndpoint(config.aws.region),
          this.discoverS3Buckets(),
        ]);

        iotEndpoint = discoveredEndpoint;
        s3BucketName = discoveredBuckets[0] || '';

        // Cache the results
        this.setCachedResults({
          iotEndpoint,
          s3Buckets: discoveredBuckets,
        });
      }

      // Use manual overrides if provided
      if (config.services.s3BucketName) {
        s3BucketName = config.services.s3BucketName;
        console.log('Using manual S3 bucket override:', s3BucketName);
      }

      if (config.services.mqttTopic) {
        mqttTopic = config.services.mqttTopic;
        console.log('Using manual MQTT topic override:', mqttTopic);
      } else {
        // Use default topic
        mqttTopic = 'dashboard/messages';
      }

      const serviceConfig: ServiceConfiguration = {
        iotEndpoint,
        s3BucketName,
        mqttTopic,
        region: config.aws.region,
      };

      console.log('Service configuration ready:', {
        iotEndpoint: serviceConfig.iotEndpoint,
        s3BucketName: serviceConfig.s3BucketName,
        mqttTopic: serviceConfig.mqttTopic,
        region: serviceConfig.region,
      });

      return serviceConfig;
    } catch (error) {
      console.error('Failed to get default configuration:', error);
      throw new Error(
        `Service discovery failed: ${error instanceof Error ? error.message : 'Unknown error'}`
      );
    }
  }

  /**
   * Clear cached discovery results
   */
  clearCache(): void {
    localStorage.removeItem(CACHE_KEY);
    console.log('Discovery cache cleared');
  }

  /**
   * Check if discovery cache is valid
   */
  isCacheValid(): boolean {
    const cached = this.getCachedResults();
    return cached !== null;
  }
}

// Export singleton instance
export const discoveryService = new DiscoveryService();
