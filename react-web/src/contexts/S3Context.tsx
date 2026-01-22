/**
 * S3 Context - Manages S3 state and provides real S3 operations
 * SIMPLIFIED VERSION - Focus only on bucket listing
 */

import React, {
  createContext,
  useContext,
  useReducer,
  useEffect,
  useCallback,
  ReactNode,
} from 'react';
import { S3Object } from '../types/s3';
import { useAuthenticatedAWS } from '../hooks/useAuthenticatedAWS';
import { realS3Service } from '../services/realS3Service';

// S3 Context State
interface S3State {
  images: S3Object[];
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  selectedBucket: string | null;
  availableBuckets: string[];
  hasMore: boolean;
  refreshing: boolean;
  lastRefreshTime: Date | null;
  lastImageEtag: string | null;
}

// S3 Context Actions
type S3Action =
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_REFRESHING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }
  | { type: 'SET_IMAGES'; payload: { images: S3Object[]; hasMore: boolean } }
  | { type: 'SET_BUCKETS'; payload: string[] }
  | { type: 'SET_SELECTED_BUCKET'; payload: string | null }
  | { type: 'UPDATE_LAST_UPDATED' }
  | { type: 'RESET_STATE' };

// S3 Context Value
interface S3ContextValue {
  state: S3State;
  actions: {
    loadImages: (bucketName?: string, showLoading?: boolean) => Promise<void>;
    refreshImages: () => Promise<void>;
    selectBucket: (bucketName: string) => void;
    clearError: () => void;
    reset: () => void;
  };
}

// Initial state
const initialState: S3State = {
  images: [],
  loading: false,
  error: null,
  lastUpdated: null,
  selectedBucket: null,
  availableBuckets: [],
  hasMore: false,
  refreshing: false,
  lastRefreshTime: null,
  lastImageEtag: null,
};

// Reducer
function s3Reducer(state: S3State, action: S3Action): S3State {
  switch (action.type) {
    case 'SET_LOADING':
      return { ...state, loading: action.payload };
    case 'SET_REFRESHING':
      return { ...state, refreshing: action.payload };
    case 'SET_ERROR':
      return {
        ...state,
        error: action.payload,
        loading: false,
        refreshing: false,
      };
    case 'SET_IMAGES':
      return {
        ...state,
        images: action.payload.images,
        hasMore: action.payload.hasMore,
        loading: false,
        refreshing: false,
        error: null,
        lastImageEtag: action.payload.images[0]?.etag || null,
      };
    case 'SET_BUCKETS':
      return { ...state, availableBuckets: action.payload };
    case 'SET_SELECTED_BUCKET':
      return { ...state, selectedBucket: action.payload };
    case 'UPDATE_LAST_UPDATED':
      return { ...state, lastUpdated: new Date() };
    case 'RESET_STATE':
      return initialState;
    default:
      return state;
  }
}

// Create context
const S3Context = createContext<S3ContextValue | undefined>(undefined);

// S3 Provider Props
interface S3ProviderProps {
  children: ReactNode;
  autoRefreshInterval?: number;
  maxImages?: number;
}

// S3 Provider Component
export const S3Provider: React.FC<S3ProviderProps> = ({
  children,
  maxImages = 50,
}) => {
  const [state, dispatch] = useReducer(s3Reducer, initialState);
  const { credentials, isAuthenticated, region } = useAuthenticatedAWS();

  /**
   * Load available buckets - Simplified for manual bucket input
   */
  const loadBuckets = useCallback(async () => {
    if (!isAuthenticated || !credentials) {
      console.log('Not authenticated, skipping bucket loading');
      return;
    }

    // No automatic bucket loading - user will input bucket name manually
    console.log('Ready for manual bucket input');

    // Check if there's a default bucket in environment
    const envBucket = process.env.REACT_APP_S3_BUCKET_NAME;
    if (envBucket && !state.selectedBucket) {
      console.log(` Using default bucket from environment: ${envBucket}`);
      dispatch({ type: 'SET_SELECTED_BUCKET', payload: envBucket });
    }
  }, [isAuthenticated, credentials, state.selectedBucket]);

  /**
   * Load images from S3 bucket
   */
  const loadImages = useCallback(
    async (bucketName?: string, showLoading = true) => {
      const targetBucket = bucketName || state.selectedBucket;

      if (!isAuthenticated || !credentials || !targetBucket) {
        const errorMsg = !targetBucket
          ? 'No bucket selected'
          : 'Authentication required';
        console.log(` Cannot load images: ${errorMsg}`);
        dispatch({ type: 'SET_ERROR', payload: errorMsg });
        return;
      }

      try {
        console.log(` Loading images from bucket: ${targetBucket}`);

        if (showLoading) {
          dispatch({ type: 'SET_LOADING', payload: true });
        } else {
          dispatch({ type: 'SET_REFRESHING', payload: true });
        }

        dispatch({ type: 'SET_ERROR', payload: null });

        // Initialize the real S3 service
        realS3Service.initialize(credentials, region);

        // List actual images from S3 (now returns only latest image)
        const result = await realS3Service.listImages(
          targetBucket,
          undefined,
          maxImages
        );

        dispatch({
          type: 'SET_IMAGES',
          payload: {
            images: result.objects,
            hasMore: result.isTruncated,
          },
        });

        dispatch({ type: 'UPDATE_LAST_UPDATED' });

        console.log(
          ` Successfully loaded ${result.objects.length} images from bucket: ${targetBucket}`
        );
      } catch (error) {
        const errorMessage =
          error instanceof Error ? error.message : 'Failed to load images';
        console.error('Failed to load images:', error);
        dispatch({ type: 'SET_ERROR', payload: errorMessage });
      }
    },
    [isAuthenticated, credentials, region, state.selectedBucket, maxImages]
  );

  /**
   * Refresh images with intelligent throttling
   */
  const refreshImages = useCallback(async () => {
    // Throttling: Don't refresh if we just refreshed within the last 5 seconds
    const now = new Date();
    const minRefreshInterval = 5000; // 5 seconds minimum between refreshes
    
    if (state.lastRefreshTime) {
      const timeSinceLastRefresh = now.getTime() - state.lastRefreshTime.getTime();
      if (timeSinceLastRefresh < minRefreshInterval) {
        console.log(`⏱ Throttling refresh: Only ${timeSinceLastRefresh}ms since last refresh (min: ${minRefreshInterval}ms)`);
        return;
      }
    }

    // Update refresh time immediately to prevent concurrent calls
    dispatch({ type: 'UPDATE_LAST_UPDATED' });
    
    console.log('Refreshing images with performance optimizations...');
    await loadImages(undefined, false);
  }, [loadImages, state.lastRefreshTime]);

  /**
   * Select bucket
   */
  const selectBucket = useCallback((bucketName: string) => {
    console.log(` Selecting bucket: ${bucketName}`);
    dispatch({ type: 'SET_SELECTED_BUCKET', payload: bucketName });
  }, []);

  /**
   * Clear error
   */
  const clearError = useCallback(() => {
    dispatch({ type: 'SET_ERROR', payload: null });
  }, []);

  /**
   * Reset state
   */
  const reset = useCallback(() => {
    console.log('Resetting S3 state');
    dispatch({ type: 'RESET_STATE' });
  }, []);

  // Load buckets when authenticated
  useEffect(() => {
    if (isAuthenticated && credentials) {
      console.log('Authentication detected, loading buckets...');
      loadBuckets();
    } else {
      console.log('Not authenticated, resetting state');
      reset();
    }
  }, [isAuthenticated, credentials, loadBuckets, reset]);

  // Load images when bucket is selected
  useEffect(() => {
    if (state.selectedBucket && isAuthenticated) {
      console.log(
        ` Bucket selected (${state.selectedBucket}), loading images...`
      );
      loadImages(state.selectedBucket, true);
    }
  }, [state.selectedBucket, isAuthenticated, loadImages]);

  // Poll S3 metadata to detect image updates
  useEffect(() => {
    if (!state.selectedBucket || !isAuthenticated || !credentials) {
      return;
    }

    const pollInterval = 5000;
    console.log(` Starting metadata polling (every ${pollInterval}ms)`);

    const intervalId = setInterval(async () => {
      try {
        realS3Service.initialize(credentials, region);
        const metadata = await realS3Service.getLatestImageMetadata(state.selectedBucket!);
        
        if (metadata && metadata.etag !== state.lastImageEtag) {
          console.log('New image detected, refreshing...');
          await loadImages(undefined, false);
        }
      } catch (error) {
        console.error('Metadata polling error:', error);
      }
    }, pollInterval);

    return () => {
      console.log('Stopping metadata polling');
      clearInterval(intervalId);
    };
  }, [state.selectedBucket, state.lastImageEtag, isAuthenticated, credentials, region, loadImages]);

  const contextValue: S3ContextValue = {
    state,
    actions: {
      loadImages,
      refreshImages,
      selectBucket,
      clearError,
      reset,
    },
  };

  return (
    <S3Context.Provider value={contextValue}>{children}</S3Context.Provider>
  );
};

// Hook to use S3 context
export const useS3 = (): S3ContextValue => {
  const context = useContext(S3Context);
  if (context === undefined) {
    throw new Error('useS3 must be used within an S3Provider');
  }
  return context;
};

// Export context for advanced usage
export { S3Context };
