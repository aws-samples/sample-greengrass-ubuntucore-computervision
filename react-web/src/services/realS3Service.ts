/**
 * Real S3 Service - Uses authenticated Cognito credentials to access actual S3 buckets
 */

import {
  S3Client,
  ListBucketsCommand,
  ListObjectsV2Command,
  GetObjectCommand,
  HeadObjectCommand,
} from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import {
  S3Object,
  S3ListResult,
  S3Error,
  SupportedImageFormat,
} from '../types/s3';

export class RealS3Service {
  private s3Client: S3Client | null = null;
  private credentials: any = null;
  private region: string = '';

  /**
   * Initialize S3 client with authenticated credentials
   */
  initialize(credentials: any, region: string): void {
    console.log('Initializing Real S3 Service...');
    console.log('Region:', region);

    this.credentials = credentials;
    this.region = region;

    this.s3Client = new S3Client({
      region,
      credentials,
    });

    console.log('Real S3 Service initialized successfully');
  }

  /**
   * Test credentials by resolving them
   */
  private async testCredentials(): Promise<void> {
    try {
      console.log('Testing credential resolution...');

      if (this.credentials && typeof this.credentials === 'function') {
        const resolvedCreds = await this.credentials();
        console.log('Credentials resolved successfully:', {
          accessKeyId: resolvedCreds.accessKeyId
            ? '***' + resolvedCreds.accessKeyId.slice(-4)
            : 'missing',
          secretAccessKey: resolvedCreds.secretAccessKey ? '***' : 'missing',
          sessionToken: resolvedCreds.sessionToken ? '***' : 'missing',
        });
      } else {
        console.warn(
          ' Credentials are not a function:',
          typeof this.credentials
        );
      }
    } catch (error) {
      console.error('Failed to resolve credentials:', error);
      throw error;
    }
  }

  /**
   * Create standardized S3 error
   */
  private createS3Error(error: any, message: string): S3Error {
    console.error('S3 Error Details:', {
      name: error?.name,
      message: error?.message,
      code: error?.Code,
      statusCode: error?.$metadata?.httpStatusCode,
      requestId: error?.$metadata?.requestId,
    });

    return {
      code: error?.name || error?.Code || 'S3Error',
      message: `${message}: ${error?.message || 'Unknown error'}`,
      statusCode: error?.$metadata?.httpStatusCode || 0,
      retryable: error?.$retryable?.throttling || false,
    };
  }

  /**
   * List all S3 buckets using authenticated credentials
   */
  async listBuckets(): Promise<string[]> {
    if (!this.s3Client) {
      throw new Error('S3 service not initialized');
    }

    try {
      console.log('Listing S3 buckets...');

      // Test credentials first
      await this.testCredentials();

      const command = new ListBucketsCommand({});
      console.log('Sending ListBuckets command...');

      const response = await this.s3Client.send(command);
      console.log('ListBuckets response received');

      if (!response.Buckets) {
        console.log('No S3 buckets found in response');
        return [];
      }

      const buckets = response.Buckets.map((bucket) => bucket.Name).filter(
        Boolean
      ) as string[];

      console.log(' Found', buckets.length, 'S3 buckets:', buckets);
      return buckets;
    } catch (error) {
      console.error('Failed to list S3 buckets:', error);

      // Provide specific error messages based on error type
      if (error instanceof Error) {
        if (error.message.includes('Failed to fetch')) {
          throw new Error(
            'Network error: Unable to connect to AWS S3. Check your internet connection and AWS region.'
          );
        } else if (error.message.includes('NetworkingError')) {
          throw new Error(
            'Network connectivity issue: Please check your internet connection.'
          );
        } else if (error.message.includes('UnknownEndpoint')) {
          throw new Error(
            'Invalid AWS region configuration. Please check your region setting.'
          );
        } else if (
          error.message.includes('AccessDenied') ||
          error.message.includes('Forbidden')
        ) {
          throw new Error(
            'Access denied: Your authenticated role does not have permission to list S3 buckets. Please check your IAM permissions.'
          );
        } else if (error.message.includes('InvalidAccessKeyId')) {
          throw new Error(
            'Invalid credentials: Please check your Cognito Identity Pool configuration.'
          );
        } else if (error.message.includes('SignatureDoesNotMatch')) {
          throw new Error(
            'Authentication error: Invalid signature. Please try signing out and back in.'
          );
        }
      }

      throw this.createS3Error(error, 'Failed to list S3 buckets');
    }
  }

  /**
   * Check if a file is a supported image format
   */
  private isImageFile(key: string): boolean {
    const supportedFormats: SupportedImageFormat[] = [
      'jpg',
      'jpeg',
      'png',
      'gif',
      'webp',
      'svg',
    ];

    const extension = key
      .toLowerCase()
      .split('.')
      .pop() as SupportedImageFormat;
    return supportedFormats.includes(extension);
  }

  /**
   * Generate signed URL for S3 object
   */
  private async generateSignedUrl(
    bucketName: string,
    key: string,
    expiresIn: number = 3600
  ): Promise<string> {
    if (!this.s3Client) {
      throw new Error('S3 service not initialized');
    }

    try {
      const command = new GetObjectCommand({
        Bucket: bucketName,
        Key: key,
      });

      const signedUrl = await getSignedUrl(this.s3Client, command, {
        expiresIn,
      });

      return signedUrl;
    } catch (error) {
      console.error('Failed to generate signed URL for:', key, error);
      throw this.createS3Error(
        error,
        `Failed to generate signed URL for ${key}`
      );
    }
  }

  /**
   * Get the latest inference image metadata (without downloading)
   */
  async getLatestImageMetadata(
    bucketName: string
  ): Promise<{ lastModified: Date; etag: string } | null> {
    if (!this.s3Client) {
      throw new Error('S3 service not initialized');
    }

    try {
      const key = 'camera/latest-inference.jpg';
      const command = new HeadObjectCommand({
        Bucket: bucketName,
        Key: key,
      });

      const response = await this.s3Client.send(command);
      
      if (response.LastModified && response.ETag) {
        return {
          lastModified: response.LastModified,
          etag: response.ETag,
        };
      }
      
      return null;
    } catch (error: any) {
      if (error?.name === 'NoSuchKey' || error?.name === 'NotFound') {
        return null;
      }
      console.error('Failed to get image metadata:', error);
      throw this.createS3Error(error, 'Failed to get image metadata');
    }
  }

  /**
   * List images from S3 bucket - Simplified to return only the latest image
   */
  async listImages(
    bucketName: string,
    prefix?: string,
    maxKeys?: number
  ): Promise<S3ListResult> {
    if (!this.s3Client) {
      throw new Error('S3 service not initialized');
    }

    try {
      console.log(' Fetching latest image from bucket:', bucketName);

      const key = 'camera/latest-inference.jpg';
      
      // Check if the image exists using GetObjectCommand
      const command = new GetObjectCommand({
        Bucket: bucketName,
        Key: key,
      });

      const response = await this.s3Client.send(command);
      
      if (!response.LastModified) {
        console.log('No image metadata found');
        return {
          objects: [],
          isTruncated: false,
          totalCount: 0,
        };
      }

      // Generate signed URL for the image
      const signedUrl = await this.generateSignedUrl(bucketName, key);

      const imageObject: S3Object = {
        key,
        lastModified: response.LastModified,
        size: response.ContentLength || 0,
        url: signedUrl,
        etag: response.ETag,
      };

      console.log(' Found latest image:', key, '(', response.LastModified.toISOString(), ')');

      return {
        objects: [imageObject],
        isTruncated: false,
        totalCount: 1,
      };
    } catch (error: any) {
      if (error?.name === 'NoSuchKey') {
        console.log('Latest image not yet available');
        return {
          objects: [],
          isTruncated: false,
          totalCount: 0,
        };
      }
      console.error('Failed to fetch latest image:', error);
      throw this.createS3Error(error, 'Failed to fetch latest image from S3');
    }
  }

  /**
   * Test S3 connection and permissions
   */
  async testConnection(): Promise<boolean> {
    if (!this.s3Client) {
      return false;
    }

    try {
      console.log('Testing S3 connection...');
      await this.listBuckets();
      console.log('S3 connection test successful');
      return true;
    } catch (error) {
      console.error('S3 connection test failed:', error);
      return false;
    }
  }
}

// Export singleton instance
export const realS3Service = new RealS3Service();
