/**
 * Image Gallery Component - Displays S3 images in a responsive grid
 * Now uses S3Context for better state management and CORS handling
 */

import React, { useEffect, useCallback, useRef } from 'react';
import { useS3 } from '../../contexts/S3Context';
import { S3Object, S3Error } from '../../types/s3';
import './ImageGallery.css';

export interface ImageGalleryProps {
  className?: string;
  onImageClick?: (image: S3Object) => void;
  onError?: (error: S3Error) => void;
}

export const ImageGallery: React.FC<ImageGalleryProps> = ({
  className = '',
  onImageClick,
  onError,
}) => {
  const { state, actions } = useS3();
  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadingImagesRef = useRef<Set<string>>(new Set());

  /**
   * Handle manual refresh
   */
  const handleRefresh = useCallback(() => {
    actions.refreshImages();
  }, [actions]);

  /**
   * Handle image click
   */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleImageClick = useCallback(
    (image: S3Object) => {
      if (onImageClick) {
        onImageClick(image);
      }
    },
    [onImageClick]
  );

  /**
   * Handle image load success
   */
  const handleImageLoad = useCallback((imageKey: string) => {
    loadingImagesRef.current.delete(imageKey);
  }, []);

  /**
   * Handle image load error
   */
  const handleImageError = useCallback((imageKey: string, error: Event) => {
    console.warn('Failed to load image:', imageKey, error);
    loadingImagesRef.current.delete(imageKey);
  }, []);

  /**
   * Set up intersection observer for lazy loading
   */
  const setupIntersectionObserver = useCallback(() => {
    if (observerRef.current) {
      observerRef.current.disconnect();
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const img = entry.target as HTMLImageElement;
            const src = img.dataset.src;

            if (src && !img.src) {
              img.src = src;
              img.classList.add('image-gallery__image--loading');
              loadingImagesRef.current.add(img.dataset.key || '');
              observerRef.current?.unobserve(img);
            }
          }
        });
      },
      {
        rootMargin: '50px',
        threshold: 0.1,
      }
    );
  }, []);

  /**
   * Initialize component
   */
  useEffect(() => {
    setupIntersectionObserver();

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [setupIntersectionObserver]);

  /**
   * Update intersection observer when images change
   */
  useEffect(() => {
    if (observerRef.current && state.images.length > 0) {
      // Observe all lazy-loaded images
      const lazyImages = document.querySelectorAll(
        '.image-gallery__image[data-src]'
      );
      lazyImages.forEach((img) => {
        observerRef.current?.observe(img);
      });
    }
  }, [state.images]);

  /**
   * Handle errors from S3Context
   */
  useEffect(() => {
    if (state.error && onError) {
      onError({
        code: 'S3Error',
        message: state.error,
        statusCode: 0,
        retryable: true,
      });
    }
  }, [state.error, onError]);

  /**
   * Format file size
   */
  const formatFileSize = (bytes: number): string => {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  };

  /**
   * Format date
   */
  const formatDate = (date: Date): string => {
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(date);
  };

  /**
   * Get image filename from key
   */
  const getImageName = (key: string): string => {
    return key.split('/').pop() || key;
  };

  // Loading state
  if (state.loading && state.images.length === 0) {
    return (
      <div className={`image-gallery ${className}`}>
        <div className="image-gallery__loading">
          <div className="image-gallery__loading-spinner"></div>
          <p className="image-gallery__loading-text">Loading images...</p>
        </div>
      </div>
    );
  }

  // Error state (no images)
  if (state.error && state.images.length === 0) {
    return (
      <div className={`image-gallery ${className}`}>
        <div className="image-gallery__error">
          <svg className="image-gallery__error-icon" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <h3 className="image-gallery__error-title">Failed to Load Images</h3>
          <p className="image-gallery__error-message">{state.error}</p>
          <button
            className="image-gallery__error-retry"
            onClick={handleRefresh}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Empty state - focus on bucket selection and latest image
  if (state.images.length === 0 && !state.loading) {
    return (
      <div className={`image-gallery ${className}`}>
        <div className="image-gallery__header">
          <h3 className="image-gallery__title">S3 Image Gallery</h3>
        </div>
        <div className="image-gallery__empty">
          <svg className="image-gallery__empty-icon" width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>
          </svg>
          <h3 className="image-gallery__empty-title">No Images Available</h3>
          <p className="image-gallery__empty-message">
            {state.selectedBucket
              ? `Connected to bucket: ${state.selectedBucket}`
              : 'Please select an S3 bucket from the configuration above'}
          </p>
          {state.availableBuckets.length > 0 && (
            <p className="image-gallery__bucket-count">
              {state.availableBuckets.length} bucket(s) available in your account
            </p>
          )}
        </div>
      </div>
    );
  }

  // Main gallery view
  return (
    <div className={`image-gallery ${className}`} role="region" aria-labelledby="image-gallery-title">
      {/* Header */}
      <div className="image-gallery__header">
        <div className="image-gallery__info">
          <h3 id="image-gallery-title" className="image-gallery__title">
            S3 Images ({state.images.length})
          </h3>
          {state.selectedBucket && (
            <p className="image-gallery__bucket-info">
              Bucket: {state.selectedBucket}
            </p>
          )}
          {state.images.length > 0 && (
            <p className="image-gallery__latest-meta">
              Latest: {getImageName(state.images[0].key)} • {formatFileSize(state.images[0].size)} • {formatDate(state.images[0].lastModified)}
            </p>
          )}
        </div>
      </div>

      {/* Error banner (if error but images still showing) */}
      {state.error && state.images.length > 0 && (
        <div className="image-gallery__error-banner" role="alert" aria-live="assertive">
          <span className="image-gallery__error-banner-text">
            {state.error}
          </span>
          <button
            className="image-gallery__error-banner-close"
            onClick={actions.clearError}
            aria-label="Dismiss error message"
          >
            ×
          </button>
        </div>
      )}

      {/* Latest Image Display */}
      {state.images.length > 0 && (
        <section className="image-gallery__latest" aria-labelledby="latest-image-title">
          <img
            src={state.images[0].url}
            alt={getImageName(state.images[0].key)}
            className="image-gallery__latest-image"
            onLoad={() => handleImageLoad(state.images[0].key)}
            onError={(e) =>
              handleImageError(state.images[0].key, e.nativeEvent)
            }
          />
        </section>
      )}

      {/* Load More (if applicable) */}
      {state.hasMore && (
        <div className="image-gallery__load-more">
          <button
            className="image-gallery__load-more-button"
            onClick={() => {
              // TODO: Implement pagination
              console.log('Load more functionality to be implemented');
            }}
          >
            Load More Images
          </button>
        </div>
      )}
    </div>
  );
};
