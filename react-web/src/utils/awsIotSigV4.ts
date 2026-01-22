/**
 * AWS IoT Core SigV4 Signing Utility for WebSocket connections
 * Creates properly signed WebSocket URLs for AWS IoT Core
 */

import { createHash, createHmac } from 'crypto';

interface Credentials {
  accessKeyId: string;
  secretAccessKey: string;
  sessionToken?: string;
}

export class AwsIotSigV4 {
  /**
   * Create a signed WebSocket URL for AWS IoT Core
   */
  static createSignedUrl(
    endpoint: string,
    region: string,
    credentials: Credentials
  ): string {
    const { accessKeyId, secretAccessKey, sessionToken } = credentials;
    
    // Create timestamp
    const now = new Date();
    const amzDate = now.toISOString().replace(/[:\-]|\.\d{3}/g, '');
    const dateStamp = amzDate.substr(0, 8);
    
    // Create canonical request
    const method = 'GET';
    const canonicalUri = '/mqtt';
    const canonicalHeaders = `host:${endpoint}\n`;
    const signedHeaders = 'host';
    const payloadHash = this.sha256('');
    
    // Build query string
    const queryParams = new URLSearchParams({
      'X-Amz-Algorithm': 'AWS4-HMAC-SHA256',
      'X-Amz-Credential': `${accessKeyId}/${dateStamp}/${region}/iotdevicegateway/aws4_request`,
      'X-Amz-Date': amzDate,
      'X-Amz-SignedHeaders': signedHeaders,
    });
    
    if (sessionToken) {
      queryParams.set('X-Amz-Security-Token', sessionToken);
    }
    
    const canonicalQueryString = queryParams.toString();
    
    const canonicalRequest = [
      method,
      canonicalUri,
      canonicalQueryString,
      canonicalHeaders,
      signedHeaders,
      payloadHash
    ].join('\n');
    
    // Create string to sign
    const algorithm = 'AWS4-HMAC-SHA256';
    const credentialScope = `${dateStamp}/${region}/iotdevicegateway/aws4_request`;
    const stringToSign = [
      algorithm,
      amzDate,
      credentialScope,
      this.sha256(canonicalRequest)
    ].join('\n');
    
    // Calculate signature
    const signature = this.calculateSignature(secretAccessKey, dateStamp, region, 'iotdevicegateway', stringToSign);
    
    // Add signature to query parameters
    queryParams.set('X-Amz-Signature', signature);
    
    // Return the signed URL
    return `wss://${endpoint}/mqtt?${queryParams.toString()}`;
  }
  
  /**
   * Calculate SHA256 hash
   */
  private static sha256(data: string): string {
    return createHash('sha256').update(data, 'utf8').digest('hex');
  }
  
  /**
   * Calculate HMAC-SHA256
   */
  private static hmacSha256(key: Buffer | string, data: string): Buffer {
    return createHmac('sha256', key).update(data, 'utf8').digest();
  }
  
  /**
   * Calculate AWS SigV4 signature
   */
  private static calculateSignature(
    secretAccessKey: string,
    dateStamp: string,
    region: string,
    service: string,
    stringToSign: string
  ): string {
    const kDate = this.hmacSha256(`AWS4${secretAccessKey}`, dateStamp);
    const kRegion = this.hmacSha256(kDate, region);
    const kService = this.hmacSha256(kRegion, service);
    const kSigning = this.hmacSha256(kService, 'aws4_request');
    const signature = this.hmacSha256(kSigning, stringToSign);
    
    return signature.toString('hex');
  }
}