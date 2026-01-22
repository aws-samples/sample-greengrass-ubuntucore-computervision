/**
 * TypeScript interfaces for S3 integration
 */

export interface S3Object {
  key: string;
  lastModified: Date;
  size: number;
  url: string;
  metadata?: Record<string, string>;
  etag?: string;
}

export interface S3ListResult {
  objects: S3Object[];
  isTruncated: boolean;
  nextContinuationToken?: string;
  totalCount: number;
}

export interface S3ServiceConfig {
  bucketName: string;
  region: string;
  prefix?: string;
  maxKeys?: number;
}

export interface S3Error {
  code: string;
  message: string;
  statusCode?: number;
  retryable?: boolean;
}

export interface ImageGalleryState {
  images: S3Object[];
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  hasMore: boolean;
  nextToken?: string;
}

export interface S3ServiceState {
  connected: boolean;
  bucketName: string;
  lastSync: Date | null;
  error: S3Error | null;
  totalObjects: number;
}

export interface S3WatchOptions {
  interval?: number; // Polling interval in milliseconds
  autoStart?: boolean;
  onUpdate?: (images: S3Object[]) => void;
  onError?: (error: S3Error) => void;
}

export interface S3UploadProgress {
  loaded: number;
  total: number;
  percentage: number;
}

export interface S3UploadResult {
  key: string;
  location: string;
  bucket: string;
  etag: string;
}

// Supported image formats
export type SupportedImageFormat =
  | 'jpg'
  | 'jpeg'
  | 'png'
  | 'gif'
  | 'webp'
  | 'svg';

export interface ImageMetadata {
  width?: number;
  height?: number;
  format?: SupportedImageFormat;
  fileSize: number;
  lastModified: Date;
  contentType?: string;
}

export interface S3ObjectWithMetadata extends S3Object {
  imageMetadata?: ImageMetadata;
  thumbnailUrl?: string;
  isImage: boolean;
}
